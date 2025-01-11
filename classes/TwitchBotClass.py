import asyncio
from twitchio.ext import commands as twitch_commands

import random
import re
import json
import os
import inspect
import time

from models.task import AddMessageTask, CreateExecuteThreadTask, CreateSendChannelMessageTask

from my_modules.my_logging import create_logger
import my_modules.adjustable_sleep_task as adjustable_sleep_task

from classes.TwitchAPI import TwitchAPI

# from classes.ConsoleColoursClass import bcolors, printc
from classes import ArticleGeneratorClass
from classes.TaskManagerClass import TaskManager

from services.VibecheckService import VibeCheckService
from services.NewUsersService import NewUsersService
from services.ChatForMeService import ChatForMeService
from services.AudioService import AudioService
from services.BotEarsService import BotEars
from services.SpeechToTextService import SpeechToTextService
from services.ExplanationService import ExplanationService
from services.FaissService import FAISSService

runtime_logger_level = 'INFO'

class Bot(twitch_commands.Bot):
    loop_sleep_time = 4

    def __init__(
            self, 
            config, 
            gpt_client, 
            bq_uploader, 
            tts_client, 
            gpt_thread_mgr, 
            gpt_assistant_mgr,
            gpt_response_mgr,
            gpt_function_call_mgr,
            message_handler,
            twitch_auth
            ):
        
        self.config = config
        self.config.twitch_bot_access_token = os.getenv('TWITCH_BOT_ACCESS_TOKEN')

        super().__init__(
            token=self.config.twitch_bot_access_token,
            name=config.twitch_bot_username,
            prefix='!',
            initial_channels=[self.config.twitch_bot_channel_name],
            nick = 'chatzilla_ai'
        )

        self.logger = create_logger(
            dirname='log', 
            logger_name='TwitchBotClass', 
            debug_level=runtime_logger_level,
            mode='w',
            stream_logs=True,
            encoding='UTF-8'
            )
        
        # dependencies instances
        self.gpt_client = gpt_client
        self.bq_uploader = bq_uploader 
        self.tts_client = tts_client
        self.message_handler = message_handler

        # Initialize the FAISSService
        self.faiss_service = FAISSService()

        # Initialize the GPTAssistantManager Classes
        self.gpt_assistant_manager = gpt_assistant_mgr
        
        # Initialize the TaskManager
        self.task_manager = self.message_handler.task_manager
        self.task_manager.on_task_ready = self.handle_tasks
        self.loop.create_task(self.task_manager.task_scheduler())

        # Create thread manager, Assigning handle_tasks to the on_task_ready event
        self.gpt_thread_mgr = gpt_thread_mgr

        # Create response manager
        self.gpt_response_manager = gpt_response_mgr

        # Create function call manager
        self.gpt_function_call_manager = gpt_function_call_mgr

        # TODO: Could be a good idea to inject these dependencies into the services
        # instantiate the ChatForMeService
        self.chatforme_service = ChatForMeService(
            tts_client=self.tts_client, #NOTE: Might also be able to use the self.gpt_client here
            send_channel_message=self._send_channel_message_wrapper
            )

        # TODO: Could be a good idea to inject these dependencies into the services
        # instantiate the NewUsersService
        self.newusers_service = NewUsersService()

        # TODO: Could be a good idea to inject these dependencies into the services
        # instantiate the AudioService and BotEars
        self.audio_service = AudioService(volume=self.config.tts_volume)
        device_name = self.config.chatzilla_mic_device_name
        botears_audio_filepath = os.path.join(config.botears_audio_path, config.botears_audio_filename)
        self.bot_ears = BotEars(
            audio_filepath=botears_audio_filepath,
            device_name=device_name,
            buffer_length_seconds=self.config.botears_buffer_length_seconds
            )

        # TODO: Could be a good idea to inject these dependencies into the services
        # Instantiate the speech to text service
        self.s2t_service = SpeechToTextService()

        # Instantiate the explanation service
        self.explanation_service = ExplanationService(
            config=self.config,
            task_manager=self.task_manager,
            message_handler=self.message_handler
            )

        #Taken from app authentication class() 
        # TODO: Reudndant with twitchAPI?
        self.twitch_auth = twitch_auth

        # Grab the TwitchAPI class and set the bot/broadcaster/moderator IDs
        self.twitch_api = TwitchAPI()

        #Get historic stream viewers
        # TODO: Should mb be refreshed more frequently)
        self.historic_users_at_start_of_session = self.bq_uploader.fetch_unique_usernames_from_bq_as_list()

        #Set default loop state
        self.is_ouat_loop_active = False
        self.vibecheck_service = None
        self.is_vibecheck_loop_active = False

        #counters
        self.ouat_counter = 0

        #NOTE: ARGUABLY DO NOT NEED TO INITIALIZE THESE HERE
        # BQ Table IDs
        self.userdata_table_id=self.config.talkzillaai_userdata_table_id
        self.usertransactions_table_id=self.config.talkzillaai_usertransactions_table_id

        # Initialize the twitch bot's channel and user IDs
        self.twitch_bot_client_id = self.config.twitch_bot_client_id
        self.logger.info(f"Twitch bot is now initialized")
        self.logger.debug(f"Twitch bot is now initialized with the following client ID: {self.twitch_bot_client_id}")

        # register commands
        self._register_chat_commands()

    def _register_chat_commands(self):
            self.add_command(twitch_commands.command(
                name='explain', 
                aliases=("p_explain"))(self.explanation_service.explanation_start)
                )
            self.add_command(twitch_commands.command(
                name='stopexplain', 
                aliases=("m_stopexplain", 'stopexplanation'))(self.explanation_service.stop_explanation)
                )

    async def _add_message_to_specified_thread(self, message_content: str, role: str, thread_name: str) -> None:
        if thread_name in self.config.gpt_thread_names:
            try:
                message_object = await self.gpt_response_manager.add_message_to_thread(
                    message_content=message_content,
                    thread_name=thread_name,
                    role=role
                )
                self.logger.debug(f"Message object: {message_object}")
            except Exception as e:
                self.logger.error(f"Error occurred in 'add_message_to_thread': {e}", exc_info=True)
        else:
            self.logger.error(f"Thread name '{thread_name}' is not in the list of thread names. Message content: {message_content[0:25]+'...'}")

    async def handle_tasks(self, task: object):
        
        try:
            task_type = task.task_dict.get("type")
            thread_name = task.task_dict.get("thread_name")
            message_role = task.task_dict.get("message_role")
            self.logger.info(f"Handling task type '{task_type}' for thread: {thread_name}")

        except Exception as e:
            self.logger.info(f"Error occurred in 'handle_tasks': {e}")

        if task_type == "add_message":
            # Add the message to the 'chatformemsgs' thread if not already handled by the GPT assistant
            # Note: Only situation where this is used is when a command needs to be sent to the thread
            content = task.task_dict.get("content")

            try:
                await self._add_message_to_specified_thread(
                    message_content=content, 
                    role=message_role,
                    thread_name=thread_name
                    )
                task.future.set_result(f"...'{task_type}' Completed")
                self.logger.info(f"...'{task_type}' task handled for thread: {thread_name}")

            except Exception as e: 
                self.logger.error(f"...Error occurred in '_add_message_to_specified_thread': {e}", exc_info=True)
                task.future.set_exception(e)

        elif task_type == "execute_thread":

            # # NOTE: if we decide to bulk add (to reduce api calls and speedup the app), 
            # #  this is where we should dump message queue into thread history
            # await self.message_handler.dump_message_queue_into_thread_history(
            #     thread_name=thread_name
            #     message_history=message_history
            #     )
 
            assistant_name = task.task_dict.get("assistant_name")
            thread_instructions = task.task_dict.get("thread_instructions")
            replacements_dict = task.task_dict.get("replacements_dict")
            tts_voice = task.task_dict.get("tts_voice")
            bool_send_channel_message = task.task_dict.get("send_channel_message")          
            
            # Execute the thread
            try:
                gpt_response = await self.gpt_response_manager.execute_thread( 
                    thread_name=thread_name, 
                    assistant_name=assistant_name, 
                    thread_instructions=thread_instructions,
                    replacements_dict=replacements_dict
                )
                self.logger.info(f"...GPT Response successfully generated for thread: {thread_name}")
                self.logger.debug(f"...GPT response: {gpt_response}")

            except Exception as e:
                gpt_response = None
                message = f"...Error occurred in '{task_type}': {e}"
                task.future.set_exception(message)
                self.logger.error(message)

            # Send the GPT response to the channel
            if gpt_response is not None and bool_send_channel_message is True:
                try:
                    # Send the GPT response to the channel
                    await self.chatforme_service.send_output_message_and_voice(
                        text=gpt_response,
                        incl_voice=self.config.tts_include_voice,
                        voice_name=tts_voice
                    )
                    message = f"...'{task_type}' task handled for thread: {thread_name}. Send channel message is True"
                    task.future.set_result(message)
                    self.logger.info(message) 

                except Exception as e:
                    message = f"...Error occurred in 'send_output_message_and_voice': {e}"
                    self.logger.error(message)
                    task.future.set_exception(message)

            if gpt_response is None:
                message = f"...Gpt response is None, this should not happen.  Task: {task.task_dict}"
                self.logger.error(message)
                task.future.set_exception(message)
            
            if bool_send_channel_message is False:
                message = f"...'{task_type}' task handled for thread: {thread_name}. Send channel message is False"
                task.future.set_result(message)
                self.logger.info(message)
            
        elif task_type == "send_channel_message":
            content = task.task_dict.get("content")
            tts_voice = task.task_dict.get("tts_voice")

            try:
                # Add the message to the 'chatformemsgs' thread if not already handled by the GPT assistant
                await self._add_message_to_specified_thread(
                    message_content=content, 
                    role=message_role, 
                    thread_name=thread_name
                    )

            except Exception as e:
                message = f"...Error occurred in 'add_message_to_thread': {e}"
                self.logger.error(message)
                task.future.set_exception(message)

            try:
                await self.chatforme_service.send_output_message_and_voice(
                    text=content,
                    incl_voice=self.config.tts_include_voice,
                    voice_name=tts_voice
                )
                message = f"...'{task_type}' task handled for thread: {thread_name}"
                task.future.set_result(message)
                self.logger.info(message)

            except Exception as e:
                message = f"...Error occurred in 'send_channel_message': {e}"
                self.logger.error(message)
                task.future.set_exception(message)
        
        else:
            message = f"Unknown task type 'task_type' found, this should not happen"
            self.logger.info(message)  
            self.future.set_exception(message)

    async def event_ready(self):
        self.channel = self.get_channel(self.config.twitch_bot_channel_name)
        self.logger.info(f'TwitchBot ready on channel {self.channel} | {self.config.twitch_bot_username} (nick:{self.nick})')

        # initialize the event loop
        self.logger.debug(f"Initializing event loop")
        self.loop = asyncio.get_event_loop()

        # start OUAT loop
        self.logger.debug(f"Starting OUAT service")
        self.loop.create_task(self.ouat_storyteller_task())

        # Start bot ears streaming
        self.logger.debug(f"Starting bot ears streaming")
        self.loop.create_task(self.bot_ears.start_botears_audio_stream())

        # start authentication refresh loop
        self.logger.debug('Starting the refresh token service')
        self.loop.create_task(self._refresh_access_token_task())

        # start randomfact loop
        self.logger.debug('Starting the randomfact service')
        self.loop.create_task(self.randomfact_task())

        # start explanation loop
        self.logger.debug('Starting the explanation service')
        self.loop.create_task(self.explanation_service.explanation_task())
 
        # Create Assistants and Threads
        self.assistants = self.gpt_assistant_manager.create_assistants(
            assistants_config=self.config.gpt_assistants_config
            )
        self.assistants_with_functions = self.gpt_assistant_manager.create_assistants_with_functions(
            assistants_with_functions=self.config.gpt_assistants_with_functions_config
            )
        self.threads = self.gpt_thread_mgr.create_threads(
            thread_names=self.config.gpt_thread_names
            )
        
        # start newusers loop
        if self.config.twitch_bot_gpt_new_users_service is True:
            self.logger.debug(f"Starting newusers service")
            self.loop.create_task(self._send_message_to_new_users_task())
        else:
            self.logger.debug(f"New Users service is disabled")

        # send hello world message
        if self.config.twitch_bot_gpt_hello_world == True:
            self.logger.debug(f"Sending hello world message")
            await self._send_hello_world_message()
        else:
            self.logger.debug(f"Hello World message is disabled")

    async def event_message(self, message):

        thread_name = 'chatformemsgs'

        def _clean_message_content(content, command_spellings) -> str:
            content_temp = content
            if content.startswith('!'):
                words = content.split(' ')
                words[0] = words[0].lower()
                content_temp = ' '.join(words)

            for correct_command, misspellings in command_spellings.items():
                for misspelled in misspellings:
                    # Using a regular expression to match whole commands only
                    pattern = r'(^|\s)' + re.escape(misspelled) + r'(\s|$)'
                    content_temp = re.sub(pattern, r'\1' + correct_command + r'\2', content_temp)
            return content_temp

        self.logger.info("---------------------------------------")
        self.logger.info("MESSAGE RECEIVED: Processing message...")

        # Get message metadata
        message_metadata = self.message_handler._get_message_metadata(message)
        message_metadata['content'] = _clean_message_content(
            message.content,
            self.config.command_spellcheck_terms
            )

        self.logger.info(f"Message from: {message_metadata['message_author']}")
        self.logger.info(f"Message content: '{message_metadata['content']}'")
        self.logger.debug(f"This is the message object {message_metadata}")

        # 1b. Add the message to the appropriate message history (not to be confused with the thread history)
        await self.message_handler.add_to_appropriate_message_history(message_metadata)
        if message_metadata['message_author'] is not None:
            await self.message_handler.add_to_thread_history(
                thread_name=thread_name,
                message_metadata=message_metadata
                )
            
            # TODO / NOTE: Could move this directly inside the 'add_to_apprioriate...' method 
            self.logger.info(f"type(message_metadata) sent to add_message_to_index: {type(message_metadata)}")
            self.logger.info(f"message_metadata sent to add_message_to_index: {message_metadata}")
            await self.faiss_service.add_message_to_index(message_metadata)

        # 1c. if message contains "@chatzilla_ai" (botname) and does not include "!chat", execute a command...
        if self.config.twitch_bot_username in message_metadata['content'] and "!chat" not in message_metadata['content'] and message.author is not None:
            await self._chatforme_main(message_metadata['content'])

        # 2. Process the message through the vibecheck service.
            #NOTE: Should this be a separate task?    
        self.logger.debug("Processing message through the vibecheck service...")

        if self.vibecheck_service is not None and self.vibecheck_service.is_vibecheck_loop_active:
            await self.vibecheck_service.process_vibecheck_message(
                message_username=message_metadata['name'],
                message_content=message_metadata['content']
                )

        # TODO: Steps 3 and 4 should probably be added to a task so they can run on a separate thread
        # 3. Get chatter data, store in queue, generate query for sending to BQ
        # 4. Send the data to BQ when queue is full.  Clear queue when done
        if len(self.message_handler.message_history_raw)>=2:

            channel_viewers_queue_query = await self.twitch_api.generate_viewers_merge_query(
                table_id=self.userdata_table_id,
                bearer_token=self.config.twitch_bot_access_token
                )

            self.bq_uploader.execute_query_on_bigquery(query=channel_viewers_queue_query)            
            viewer_interaction_records = self.bq_uploader.generate_twitch_user_interactions_records_for_bq(
                records=self.message_handler.message_history_raw
                )

            self.logger.debug(f"viewer_interaction_records: {viewer_interaction_records}")

            self.bq_uploader.send_recordsjob_to_bq(
                table_id=self.usertransactions_table_id,
                records=viewer_interaction_records
                )

            self.logger.info(f"Clearing message_history_raw and channel_viewers_queue.")
            self.logger.debug(f"MESSAGE HISTORY RAW PRE-CLEAR: {self.message_handler.message_history_raw}")
            self.logger.debug(f"CHANNEL VIEWERS QUEUE PRE-CLEAR: {self.twitch_api.channel_viewers_queue}")
            
            self.message_handler.message_history_raw.clear()
            self.twitch_api.channel_viewers_queue.clear()

        # 5. self.handle_commands runs through bot commands
        if message_metadata['message_author'] is not None:
            await self.handle_commands(message)

        self.logger.info("MESSAGE PROCESSED: Done processing message")     
        self.logger.info("---------------------------------------")

    def retrieve_registered_commands_info(self):
        commands_info = []
        for command_name, command_obj in self.commands.items():
            aliases = command_obj.aliases
            command_info = {
                "name": command_name,
                "aliases": aliases,
            }
            #has more than just aliases?
            self.logger.info(f"command_obj: {command_obj}")
            
            #result
            self.logger.debug(f"Command info: {command_info}")
            commands_info.append(command_info)
        return commands_info
    
    async def _refresh_access_token_task(self):
        while True:
            try:
                current_time = time.time()
                if self.twitch_auth.access_token_expiry <= current_time:
                    self.logger.warning("Access Token near expiry, generating new access token using the refresh token...")
                    response = await self.twitch_auth.refresh_access_token()
                    tokens = response.json()
                    
                    # Calculate the new expiry time for the access token
                    new_expiry_time = current_time + int(tokens['expires_in']) - 3600
                    
                    self.twitch_auth.access_token_expiry = new_expiry_time
                    self.twitch_auth.handle_auth_callback(response)
                else:
                    self.logger.debug("Access token not nearing expiry. No need to refresh.")
            except Exception as e:
                self.logger.error(f"Failed to refresh Twitch access token: {e}")
            
            # Wait for 30 minutes before checking again
            await asyncio.sleep(1800)

    async def _send_message_to_new_users_task(self, thread_name='chatformemsgs', assistant_name='newuser_shoutout'):
        self.current_users_list = []
        tts_voice_selected = self.config.tts_voice_newuser

        while True:
            await adjustable_sleep_task.adjustable_sleep_task(self.config, 'newusers_sleep_time')
            self.logger.debug("Checking for new users...")

            # Get the current users in the channel
            try:
                current_users_list = await self.twitch_api.retrieve_active_usernames(
                    bearer_token = self.config.twitch_bot_access_token
                    )
                self.logger.debug(f"...Current users retrieved: {current_users_list}")  
            except Exception as e:
                self.logger.error(f"Failed to retrieve active users from Twitch API: {e}")
                current_users_list = []
                
            # Add self.current_users_list to self.current_users_list as set to remove duplicates
            self.current_users_list = list(set(self.current_users_list + current_users_list))

            if not self.current_users_list:
                self.logger.debug("...No users in self.current_users_list, skipping this iteration.")
                continue
                
            # Identify list of users who are new to the channel and have not yet been sent a message
            users_not_yet_sent_message_info = await self.newusers_service.get_users_not_yet_sent_message(
                historic_users_list = self.historic_users_at_start_of_session,
                current_users_list = self.current_users_list,
                users_sent_messages_list = self.newusers_service.users_sent_messages_list
            )

            if not users_not_yet_sent_message_info:
                self.logger.debug("...No users not yet sent a message.")
                continue
            else:
                self.logger.debug(f"...Users not yet sent a message: {users_not_yet_sent_message_info}")

            eligible_users = [
                user for user in users_not_yet_sent_message_info
                if (user['username'] not in self.newusers_service.known_bots_list
                    and user['username'] not in self.config.twitch_bot_operatorname
                    and user['username'] not in self.config.twitch_bot_channel_name
                    and user['username'] not in self.config.twitch_bot_username
                    and user['username'] not in self.config.twitch_bot_display_name
                    #and user['username'] not in "crubeyawne"
                    #and user['username'] not in "nanovision"
                    #and user['username'] not in mods_list
                    )
            ]       
     
            if not eligible_users:
                self.logger.debug(f"...No eligible users found after filtering.")
                continue

            random_user = random.choice(eligible_users)  
            random_user_type = random_user['usertype']
            random_user_name = random_user['username'] 

            self.newusers_service.users_sent_messages_list.append(random_user_name)
            self.logger.info(f"...Selected user for new user message: {random_user_name} ({random_user_type}) for new user message.")

            # Get the user's chat history and send a message based on the user's chat history
            # - Use FAISS for semantic similarity.
            # - After you get the top-k messages, filter or rank them based on metadata stored in a separate Python dictionary or database.
            # - Feed the filtered context (including user’s name, role, and timestamps) into your prompt.
            # - Add instructions to your prompt telling the bot to "respond to a message you haven't addressed before," using the metadata you extracted to identify those messages.
            if random_user_type == "returning" and self.config.flag_returning_users_service is True:
                user_specific_chat_history = self.bq_uploader.fetch_user_chat_history_from_bq(
                    user_login=random_user_name,
                    interactions_table_id=self.config.talkzillaai_usertransactions_table_id,
                    users_table_id=self.config.talkzillaai_userdata_table_id
                )

                # Log the user-specific chat history sample
                self.logger.debug(f"...User-specific chat history Type: {type(user_specific_chat_history)}")
                self.logger.debug(f"...User-specific chat history sample: {user_specific_chat_history[0:5]}")
                
                # Use FAISS to retrieve the most relevant messages
                query_final = self.config.newusers_faiss_default_query.replace("{random_user_name}", random_user_name)
                self.logger.debug(f"...FAISS Query message search for '{random_user_name}': {query_final}")

                relevant_message_ids = self.faiss_service.build_and_retrieve_from_user_index(
                    messages=user_specific_chat_history, query=query_final
                )

                if not relevant_message_ids:
                    self.logger.debug("No relevant messages retrieved. Defaulting to no chat history message.")
                    relevant_message_history = ["No chat history available for new users."]
                    prompt = self.config.newusers_msg_prompt
                else:
                    # Retrieve only the relevant messages (no need to re-query BigQuery)
                    relevant_message_history = [
                        msg["content"]
                        for msg in user_specific_chat_history if msg["message_id"] in relevant_message_ids
                    ]
                    prompt = self.config.returningusers_msg_prompt
            else:
                relevant_message_history = ["No chat history available for new users."]
                prompt = self.config.newusers_msg_prompt

            self.logger.debug(f"type(relevant_message_history): {type(relevant_message_history)}")

            # Create task to send a message to the selected user
            try:
                replacements_dict = {
                    "random_new_user": random_user_name,
                    "wordcount_medium": self.config.wordcount_medium,
                    "user_specific_chat_history": relevant_message_history
                }

                # Add an executeTask to the queue
                task = CreateExecuteThreadTask(
                    thread_name=thread_name,
                    assistant_name=assistant_name,
                    thread_instructions=prompt,
                    replacements_dict=replacements_dict,
                    tts_voice=tts_voice_selected
                )

                await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'newusers'")

            except Exception as e:
                self.logger.exception(f"Error occurred in sending {random_user_type} user message: {e}")
                continue

    async def _send_channel_message_wrapper(self, message):
        await self.channel.send(message)

    async def _is_function_caller_moderator(self, ctx) -> bool:
        is_sender_mod = False
        command_name = inspect.currentframe().f_back.f_code.co_name
        if not ctx.message.author.is_mod:
            await self._send_channel_message_wrapper(f"Oops, the {command_name} is for mods...")
        elif ctx.message.author.is_mod:
            is_sender_mod = True
        self.logger.debug(f"...is sender a mod? '{is_sender_mod}'")
        return is_sender_mod

    async def _send_hello_world_message(self):
        # Say hello to the chat 
        if self.config.twitch_bot_gpt_hello_world == True:
            gpt_prompt_text = self.config.hello_assistant_prompt
            assistant_name = 'chatforme'
            thread_name = 'chatformemsgs'
            tts_voice = self.config.tts_voice_default

            replacements_dict = {
                "wordcount_medium":self.config.wordcount_medium,
                'twitch_bot_display_name':self.config.twitch_bot_display_name,
                'twitch_bot_channel_name':self.config.twitch_bot_channel_name,
                'param_in_text':'variable_from_scope'
                }

            # Add a executeTask to the queue
            task = CreateExecuteThreadTask(
                thread_name=thread_name,
                assistant_name=assistant_name,
                thread_instructions=gpt_prompt_text,
                replacements_dict=replacements_dict,
                tts_voice=tts_voice
            )
            await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'hello_world'")

    @twitch_commands.command(name='getstats', aliases=("p_getstats", "stats"))
    async def get_command_stats(self, ctx):
        table_id = self.config.talkzillaai_usertransactions_table_id
        stats_text = self.bq_uploader.fetch_interaction_stats_as_text(table_id)
        await self._send_channel_message_wrapper(stats_text)

    @twitch_commands.command(name='what', aliases=("m_what"))
    async def what(self, ctx):
    
        is_sender_mod = await self._is_function_caller_moderator(ctx)
        if not is_sender_mod:
            self.logger.debug("Requester was not a mod... nothing happened")
            return
    
        gpt_prompt_text = self.config.botears_prompt
        assistant_name = 'chatforme'
        thread_name = 'chatformemsgs'
        tts_voice = self.config.tts_voice_default

        # audio_path for audio save location
        audio_path = os.path.join(self.config.botears_audio_path, self.config.botears_audio_filename + ".wav")
        self.logger.debug(f"audio_path for audio save location: {audio_path}")

        await self.bot_ears.save_last_n_seconds(
            filepath=audio_path, 
            saved_seconds=self.config.botears_save_length_seconds
            )
        
        # Translate the audio to text
        text = await self.s2t_service.convert_audio_to_text(audio_path)
        self.logger.info(f"Transcribed speech to text: {text}")

        # Add to thread (This is done to send the voice message to the GPT thread)
        task = AddMessageTask(thread_name, text, message_role='user')
        await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="AddMessageTask 'what'")

        replacements_dict = {
            "wordcount_medium": self.config.wordcount_medium,
            "botears_questioncomment": text
        }

        # Add a executeTask to the queue
        task = CreateExecuteThreadTask(
            thread_name=thread_name,
            assistant_name=assistant_name,
            thread_instructions=gpt_prompt_text,
            replacements_dict=replacements_dict,
            tts_voice=tts_voice
        )
        await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'what'")

    @twitch_commands.command(name='commands', aliases=["p_commands"])
    async def showcommands(self, ctx):
        results = set()
        commands_info = self.retrieve_registered_commands_info()
        
        for command in commands_info:
            self.logger.info(f"Command Object: {command}")
            
            command_name = command['name']
            aliases = command['aliases']

            if aliases is None:
                self.logger.info(f"No aliases for command: {command_name}")
                continue

            # Normalize aliases to a list
            if isinstance(aliases, str):
                aliases = [aliases]
            elif isinstance(aliases, tuple):
                aliases = list(aliases)

            for alias in aliases:
                self.logger.info(f"Alias: {alias}")
                
                if not alias.startswith("m_"):
                    results.add(command_name)
                    
        self.logger.info(f"Results: {results}")
        
        results_string = ', '.join(sorted(results))
        self.logger.debug(f"Results string: {results_string}")
        
        await self._send_channel_message_wrapper(f"Commands include: {results_string}")

    @twitch_commands.command(name='specs', aliases=("p_specs"))
    async def specs(self, ctx):
        await self._send_channel_message_wrapper("i7-13700K || RTX 4070 Ti OC || 64GB DDR5 6400MHz || ASUS ROG Strix Z790-F")

    @twitch_commands.command(name='discord', aliases=("p_discord"))
    async def discord(self, ctx):
        await self._send_channel_message_wrapper("This is the discord server, come say hello but, ughhhhh, don't mind the mess: https://discord.gg/XdHSKaMFvG")

    @twitch_commands.command(name='github', aliases=("p_github"))
    async def github(self, ctx):
        await self._send_channel_message_wrapper("This is the github/repo if you like what you see: https://github.com/hitch-co/chatzilla_ai")

    async def _chatforme_main(self, text_input_from_user=None):
        assistant_name = 'chatforme'
        thread_name = 'chatformemsgs'
        tts_voice = self.config.tts_voice_chatforme
        chatforme_prompt = self.config.chatforme_prompt

        if text_input_from_user is None:
            text_input_from_user = 'none'

        replacements_dict = {
            "twitch_bot_display_name":self.config.twitch_bot_display_name,
            "num_bot_responses":self.config.num_bot_responses,
            "users_in_messages_list_text":self.message_handler.users_in_messages_list_text,
            "wordcount_medium":self.config.wordcount_medium,
            "bot_operatorname":self.config.twitch_bot_operatorname,
            "twitch_bot_channel_name":self.config.twitch_bot_channel_name,
            "text_input_from_user":text_input_from_user,
        }

        # Add a executeTask to the queue
        task = CreateExecuteThreadTask(
            thread_name=thread_name,
            assistant_name=assistant_name,
            thread_instructions=chatforme_prompt,
            replacements_dict=replacements_dict,
            tts_voice=tts_voice
        )
        self.logger.debug(f"Task to add to queue: {task.task_dict}")

        await self.task_manager.add_task_to_queue_and_execute(thread_name, task)
        
    # TODO: it seems like creating a task is a good idea as each individual task
    # is effectrively goign to be executed asyncronously... rather than getting blocked 
    #   Other option is potentially the process task method instead
    @twitch_commands.command(name='chat', aliases=("p_chat"))
    async def chatforme(self, ctx=None, *args):
        if args is None or len(args) == 0:
            text_input_from_user = 'none'
        else:
            text_input_from_user = ' '.join(args)

        self.loop.create_task(self._chatforme_main(text_input_from_user))

    @twitch_commands.command(name='last_message', aliases=("m_last_message",))
    async def last_message(self, ctx, *args):
        """
        Twitch command to retrieve the last message from a specified user.

        Parameters:
        - ctx: The Twitch context object.
        - *args: Command arguments (expects one argument: the username).

        Behavior:
        - Checks if the sender is a moderator.
        - Retrieves the last message from the specified user.
        - Sends the message content to the channel.
        """
        # Check if the command sender is a moderator
        is_sender_mod = await self._is_function_caller_moderator(ctx)

        if is_sender_mod:
            if len(args) == 1:  # Ensure exactly one argument is passed
                user_name = args[0]
                try:
                    # Fetch the last message from BigQuery
                    last_message_json = self.bq_uploader.fetch_user_chat_history_from_bq(
                        user_login=user_name,
                        interactions_table_id=self.config.talkzillaai_usertransactions_table_id,
                        users_table_id=self.config.talkzillaai_userdata_table_id,
                        limit=1
                    )

                    if last_message_json:  # Ensure there is at least one result
                        last_message_content = last_message_json[0].get('content', '(No content available)')
                        await self._send_channel_message_wrapper(
                            f"Last message from {user_name}: {last_message_content}"
                        )
                    else:
                        # Handle the case where no messages are found
                        await self._send_channel_message_wrapper(
                            f"No messages found for user {user_name}."
                        )
                except Exception as e:
                    self.logger.error(f"Error fetching last message for {user_name}: {e}", exc_info=True)
                    await self._send_channel_message_wrapper(
                        f"Could not retrieve messages for user {user_name}. Please try again later."
                    )
            else:
                # Handle incorrect number of arguments
                self.logger.warning(
                    f"Incorrect number of arguments ({len(args)} sent, only 1 required)."
                )
                await self._send_channel_message_wrapper(
                    "Usage: !last_message <username>"
                )
        else:
            # Handle case where sender is not a moderator
            self.logger.info(
                f"Sender is not a moderator or incorrect number of arguments ({len(args)})."
            )
            
    @twitch_commands.command(name='vc', aliases=("m_vc"))
    async def vc(self, ctx, *args):

        def _soft_username_match(username, current_users_list) -> str:
            username = username.lower()  # Convert username to lowercase
            for user in current_users_list:
                if username in user.lower():
                    return user
            return None

        def _extract_username_from_message(message, start_marker='<<<', end_marker='>>>') -> str:
            name_start_pos = message.find(start_marker)
            if name_start_pos == -1:
                return None

            name_start_pos += len(start_marker)

            name_end_pos = message.find(end_marker, name_start_pos)
            if name_end_pos == -1:
                return None
            
            return message[name_start_pos:name_end_pos]

        is_sender_mod = await self._is_function_caller_moderator(ctx)
        if not is_sender_mod:
            self.logger.debug("Requester was not a mod... nothing happened")
            return
        else:
            self.logger.debug("Starting vibecheck service...")

        # List of users to exclude from the vibecheck
        users_excluded_from_vibecheck = [
            self.config.twitch_bot_username, 
            self.config.twitch_bot_display_name,
            self.config.twitch_bot_operatorname,
            self.config.twitch_bot_channel_name,
            self.config.twitch_bot_moderators
            ]
        
        # Set the vibecheckee, vibechecker, and vibecheckbot usernames
        self.vibecheckee_username = None
        self.vibechecker_username = ctx.author.name
        self.vibecheckbot_username = self.config.twitch_bot_display_name

        # Check if the vibecheckee is specified in the command
        if len(args) == 1:
            current_users_list = await self.twitch_api.retrieve_active_usernames(
                    bearer_token = self.config.twitch_bot_access_token
                    )
            vibecheckee_username_search = args[0]
            self.vibecheckee_username = _soft_username_match(vibecheckee_username_search, current_users_list)
            self.logger.info(f"...Vibecheckee username: {self.vibecheckee_username}")

            if self.vibecheckee_username is None:
                await self._send_channel_message_wrapper(f"User '{vibecheckee_username_search}' not found in the chat, {self.vibechecker_username}")
                return
            
        # If the vibecheckee is not specified, find the most recent message with a valid user
        else:
            message_to_check = -2

            # Extract the bot/checker/checkee (important players) in the convo
            while len(self.message_handler.all_msg_history_gptdict) > abs(message_to_check):
                try:
                    most_recent_message = self.message_handler.all_msg_history_gptdict[message_to_check]['content']
                    vibecheckee_username = _extract_username_from_message(most_recent_message)
                    self.logger.info(f"...Vibecheckee username: {self.vibecheckee_username}")

                    # If the vibecheckee is not in the list of excluded users, break the loop
                    if vibecheckee_username not in users_excluded_from_vibecheck and vibecheckee_username is not None:
                        self.vibecheckee_username = vibecheckee_username
                        self.logger.info(f"...Vibecheckee username: {self.vibecheckee_username}")    
                        break
                    else:
                        # Move to the previous message if the current vibecheckee is in the list of excluded users
                        message_to_check -= 1

                    if abs(message_to_check) >= len(self.message_handler.all_msg_history_gptdict):
                        await self._send_channel_message_wrapper(f"Could not find a valid user to vibecheck, {self.vibechecker_username}")
                        return
                    
                except Exception as e:
                    self.logger.error(f"Error occurred in extracting the username from the message: {e}")
                    return
        
        if self.vibecheckee_username is None:
            await self._send_channel_message_wrapper(f"Could not find a valid user to vibecheck, {self.vibechecker_username}")
            return

        # Start the vibecheck service and then the session
        try:
            self.vibecheck_service = VibeCheckService(
                message_handler=self.message_handler,
                gpt_assistant_mgr=self.gpt_assistant_manager,
                task_manager=self.task_manager,
                gpt_response_mgr=self.gpt_response_manager,
                chatforme_service=self.chatforme_service,
                vibechecker_players= {
                    'vibecheckee_username': self.vibecheckee_username,
                    'vibechecker_username': self.vibechecker_username,
                    'vibecheckbot_username': self.vibecheckbot_username
                },
                send_channel_message=self._send_channel_message_wrapper
                )
        except Exception as e:
            self.logger.error(f"Error occurred in starting the vibecheck service: {e}")
            return
        
        # Start the vibecheck session
        await self.vibecheck_service.start_vibecheck_session()

    @twitch_commands.command(name='stop_vc', aliases=("m_stop_vc",))
    async def stop_vc(self, ctx, *args):
        # Optional: Check if the user has permission to stop the vibe check

        is_sender_mod = await self._is_function_caller_moderator(ctx)
        if not is_sender_mod:
            self.logger.debug("Requester was not a mod... nothing happened")
            return

        if self.vibecheck_service is not None:
            await self.vibecheck_service.stop_vibecheck_session()
            self.vibecheck_service = None  # Reset the reference
            await self._send_channel_message_wrapper("The vibe check has been stopped.")
        else:
            await self._send_channel_message_wrapper("There is no active vibe check to stop.")

    @twitch_commands.command(name='startstory', aliases=("p_startstory"))
    async def startstory(self, message, *args):
        self.logger.info(f"Starting story, self.ouat_counter={self.ouat_counter}")
        self.logger.info(f"args: {args}")

        # Set the thread name and assistant name
        thread_name = 'ouatmsgs'
        assistant_name = 'storyteller'
        
        if self.ouat_counter == 0:
            self.ouat_story_max_counter = self.config.ouat_story_max_counter_default
            self.ouat_counter += 1

            # Extract the user requested plotline and if '' or ' ', etc. then set to None
            if len(args) > 0:
                first_arg = args[0].strip()

                # If the first argument is a number, set the max counter to that number
                if first_arg.isnumeric():
                    self.ouat_story_max_counter = int(first_arg)
                    self.logger.info(f"Max counter set to {self.ouat_story_max_counter}")
                    user_requested_plotline_str = ' '.join(args[1:])
                else:
                    user_requested_plotline_str = ' '.join(args)
                    if user_requested_plotline_str in ['', ' ', None]:
                        user_requested_plotline_str = None  
            else:
                user_requested_plotline_str = None

            # Randomly select voice/tone/style/theme from list, set replacements dictionary
            self.current_story_voice = random.choice(self.config.tts_voices['female'])

            writing_tone_values = list(self.config.writing_tone.values())
            self.selected_writing_tone = random.choice(writing_tone_values)

            writing_style_values = list(self.config.writing_style.values())
            self.selected_writing_style = random.choice(writing_style_values)

            theme_values = list(self.config.writing_theme.values())
            self.selected_theme = random.choice(theme_values)

            # Log the story details
            self.logger.info(f"...A story was started by {message.author.name} ({message.author.id})")
            self.logger.info(f"...thread_name and assistant_name: {thread_name}, {assistant_name}")
            self.logger.info(f"...user_requested_plotline_str: {user_requested_plotline_str}")
            self.logger.info(f"...current_story_voice: {self.current_story_voice}")
            self.logger.info(f"...selected_writing_tone: {self.selected_writing_tone}")
            self.logger.info(f"...selected_writing_style: {self.selected_writing_style}")
            self.logger.info(f"...selected_theme: {self.selected_theme}")

            if user_requested_plotline_str is not None:
                submitted_plotline = user_requested_plotline_str      
                self.logger.info(f"Scheduler-2: This is the submitted plotline: {submitted_plotline}")

            elif user_requested_plotline_str is None:
                submitted_plotline = self.article_generator.fetch_random_article_content(article_char_trunc=1000)                    
                self.logger.info(f"Scheduler-2: This is the random article plotline: {submitted_plotline}")

            gpt_prompt_text = self.config.story_user_opening_scene_summary_prompt + " " + self.config.storyteller_storysuffix_prompt    
            self.logger.info(f"...OUAT gpt_prompt_text (before replacements): '{gpt_prompt_text}'")
            replacements_dict = {
                "user_requested_plotline":submitted_plotline,
                "wordcount_short":self.config.wordcount_short,
                "wordcount_medium":self.config.wordcount_medium,
                "wordcount_long":self.config.wordcount_long,
                "ouat_counter":self.ouat_counter,
                "max_ouat_counter":self.ouat_story_max_counter,
                }

            # Add executeTask to the queue
            task = CreateExecuteThreadTask(
                thread_name=thread_name,
                assistant_name=assistant_name,
                thread_instructions=gpt_prompt_text,
                replacements_dict=replacements_dict,
                tts_voice=self.current_story_voice,
                send_channel_message=True
                )
            await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'startstory'")
            self.is_ouat_loop_active = True
        else:
            # Optionally, send a message to the channel that a story is already in progress
            await self._send_channel_message_wrapper("A story is already in progress...")
            self.logger.info("A story is already in progress...")

    async def ouat_storyteller_task(self):
        self.article_generator = ArticleGeneratorClass.ArticleGenerator(rss_link=self.config.newsarticle_rss_feed)
        self.article_generator.fetch_articles()

        assistant_name = 'storyteller'
        thread_name = 'ouatmsgs'

        #This is the while loop that generates the occurring GPT response
        while True:
            if self.is_ouat_loop_active is False:
                await asyncio.sleep(self.loop_sleep_time)
                continue

            else:
                self.ouat_counter += 1
                self.logger.info(f"OUAT details: Starting cycle #{self.ouat_counter} of the OUAT Storyteller") 

                # Story progressor
                if self.ouat_counter <= self.config.ouat_story_progression_number:
                    gpt_prompt = self.config.storyteller_storyprogressor_prompt

                # Story climax
                elif self.ouat_counter <= self.config.ouat_story_climax_number:
                    gpt_prompt = self.config.storyteller_storyclimax_prompt

                # Story finisher
                elif self.ouat_counter <= self.config.ouat_story_finisher_number:
                    gpt_prompt = self.config.storyteller_storyfinisher_prompt

                # Story ender
                elif self.ouat_counter == self.ouat_story_max_counter:
                    gpt_prompt = self.config.storyteller_storyender_prompt

                # Default to progressor
                else:
                    gpt_prompt = self.config.storyteller_storyprogressor_prompt

                # Combine prefix and final article content
                gpt_prompt_final = self.config.storyteller_storysuffix_prompt + " " + gpt_prompt

                self.logger.info(f"The self.ouat_counter is currently at {self.ouat_counter} (ouat_story_max_counter={self.ouat_story_max_counter})")
                self.logger.info(f"The story has been initiated with the following storytelling parameters:\n-{self.selected_writing_style}\n-{self.selected_writing_tone}\n-{self.selected_theme}")
                self.logger.info(f"OUAT gpt_prompt_final: '{gpt_prompt_final}'")

                replacements_dict = {
                    "wordcount_short":self.config.wordcount_short,
                    "wordcount_long":self.config.wordcount_long,
                    'twitch_bot_display_name':self.config.twitch_bot_display_name,
                    'num_bot_responses':self.config.num_bot_responses,
                    'writing_style': self.selected_writing_style,
                    'writing_tone': self.selected_writing_tone,
                    'writing_theme': self.selected_theme,
                    "ouat_counter":self.ouat_counter,
                    "max_ouat_counter":self.ouat_story_max_counter,
                    'param_in_text':'variable_from_scope'
                    }

                # Add a executeTask to the queue
                task = CreateExecuteThreadTask(
                    thread_name=thread_name,
                    assistant_name=assistant_name,
                    thread_instructions=gpt_prompt_final,
                    replacements_dict=replacements_dict,
                    tts_voice=self.current_story_voice
                )
                await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'ouat_storyteller'")


            if self.ouat_counter >= self.ouat_story_max_counter:
                await self.stop_ouat_loop()
            else:
                await asyncio.sleep(int(self.config.ouat_message_recurrence_seconds))

    @twitch_commands.command(name='addtostory', aliases=("p_addtostory"))
    async def add_to_story_ouat(self, ctx,  *args):
        self.ouat_counter = self.config.ouat_story_progression_number
        
        gpt_prompt_text = ' '.join(args)
        prompt_text_with_prefix = f"{self.config.ouat_prompt_addtostory_prefix}:'{gpt_prompt_text}'"

        # Get the message metadata
        message_metadata = self.message_handler._get_message_metadata(ctx.message)

        #workflow1: get gpt_ready_msg_dict and add message to message history
        gpt_ready_msg_dict = self.message_handler._create_gpt_message_dict_from_strings(
            content=prompt_text_with_prefix,
            role='user',
            name=message_metadata['message_author'],
            timestamp=message_metadata['timestamp']
            )

        # Add the bullet list to the 'ouatmsgs' thread via queue
        thread_name = 'ouatmsgs'
        task = AddMessageTask(thread_name, gpt_prompt_text, message_role='user')
        await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="AddMessageTask 'add_to_story_ouat'")

        self.logger.info(f"A story was added to by {message_metadata['message_author']} ({message_metadata['user_id']}): '{gpt_prompt_text}'")

    @twitch_commands.command(name='extendstory', aliases=("p_extendstory"))
    async def extend_story(self, ctx, *args) -> None:
        self.ouat_counter = self.config.ouat_story_progression_number
        self.logger.info(f"Story extension requested by {ctx.message.author.name} ({ctx.message.author.id}), self.ouat_counter has been set to {self.ouat_counter}")

    @twitch_commands.command(name='stopstory', aliases=("m_stopstory"))
    async def stop_story(self, ctx):
        thread_name='ouatmsgs'
        if self.ouat_counter >= 1:
            self.logger.info(f"Story is being forced to end by {ctx.message.author.name} ({ctx.message.author.id}), counter is at {self.ouat_counter}")
        
            content = "to be continued..."
            try:
                task = CreateSendChannelMessageTask(
                    thread_name=thread_name,
                    content=content,
                    tts_voice=self.current_story_voice,
                )
                await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="SendChannelMessageTask 'stop_story'")
            
            except Exception as e:
                self.logger.error(f"Error occurred in stopping the story: {e}")
            
        await self.stop_ouat_loop()

    @twitch_commands.command(name='endstory', aliases=("m_endstory"))
    async def endstory(self, ctx):
        if self.ouat_counter > 0:
            self.ouat_counter = self.ouat_story_max_counter # May cause two endstory commands to sent
            self.logger.info(f"Story is being ended by {ctx.message.author.name} ({ctx.message.author.id}), counter is at {self.ouat_counter}")

    async def stop_ouat_loop(self) -> None:
        self.is_ouat_loop_active = False
        self.ouat_counter = 0
        self.logger.info(f"OUAT loop has been stopped, self.ouat_counter has been reset to {self.ouat_counter}")

    async def _factcheck_main(self, text_input_from_user=None):

        assistant_name = 'factchecker'
        thread_name = 'chatformemsgs'
        tts_voice = self.config.tts_voice_randomfact

        if text_input_from_user is None:
            text_input_from_user = "none"

        # select a random number/item based on the number of items inside of self.config.factchecker_prompts.values()
        random_number = random.randint(0, len(self.config.factchecker_prompts.values())-1)
        chatforme_factcheck_prompt = list(self.config.factchecker_prompts.values())[random_number]

        replacements_dict = {
            "twitch_bot_display_name":self.config.twitch_bot_display_name,
            "num_bot_responses":self.config.num_bot_responses,
            "users_in_messages_list_text":self.message_handler.users_in_messages_list_text,
            "wordcount":self.config.wordcount_medium,
            "bot_operatorname":self.config.twitch_bot_operatorname,
            "twitch_bot_channel_name":self.config.twitch_bot_channel_name,
            "factual_claim_input":text_input_from_user
        }

        try:
            
            # Add a executeTask to the queue
            task = CreateExecuteThreadTask(
                thread_name=thread_name,
                assistant_name=assistant_name,
                thread_instructions=chatforme_factcheck_prompt,
                replacements_dict=replacements_dict,
                tts_voice=tts_voice
            )
            await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'factcheck'")

        except Exception as e:
            return self.logger.error(f"error with chatforme in twitchbotclass: {e}")

    @twitch_commands.command(name='factcheck', aliases=("p_factcheck"))
    async def factcheck(self, ctx, *args):
        if args is not None and len(args) > 0:
            text_input_from_user = ' '.join(args)
        else:
            text_input_from_user = 'none'
        self.loop.create_task(self._factcheck_main(text_input_from_user))

    @twitch_commands.command(name='update_config', aliases=("m_update_config",))
    async def update_config(self, ctx, *args):
        
        self.logger.info(f"Updating config variable ...")
        is_sender_mod = await self._is_function_caller_moderator(ctx)
        if not is_sender_mod:
            self.logger.debug("Requester was not a mod... nothing happened")
            return

        # Validate input
        if len(args) < 2:
            await self.channel.send("Usage: !update_config [config_var] [value]")
            return

        # Extract the config variable and value from the command arguments
        config_var = args[0]
        value = ' '.join(args[1:])

        # If the value is true or false, make sure that the setatt() method is used to set the value to a boolean
        if value.lower() in ['true', 'false']:
            self.logger.debug(f"Value '{value}' is a boolean. It will be set as a boolean.")
            if value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False

        # If the value is an integer, make sure that the setatt() method is used to set the value to an integer
        try:
            value = int(value)
        except ValueError:
            self.logger.debug(f"Value '{value}' could not be converted to an integer. It will be set as a string.")   
            pass

        # # Dictionary of allowed config variables and their expected types
        # config_vars = {
        #     'tts_include_voice': str,
        #     'randomfact_selected_game': str,
        #     'another_config_var': int,  # Add more config variables as needed
        # }

        # # Check if the config variable is allowed
        # if config_var not in config_vars:
        #     await self.channel.send(f"Invalid config variable: {config_var}")
        #     return

        # Attempt to update the config variable
        try:
            # expected_type = config_vars[config_var]
            # if expected_type == int:
            #     value = int(value)
            # elif expected_type == str:
            #     value = str(value)
            # # Add more type checks as needed

            setattr(self.config, config_var, value)
            self.logger.info(f"Config variable '{config_var}' has been updated to '{value}'")
        except Exception as e:
            self.logger.error(f"Error occurred in !update_config: {e}")
            await self.channel.send("No change made, see log for details...")

    def _pick_random_category(self, data: dict):
        topic = random.choice(list(data.keys()))
        subtopic = random.choice(data[topic])
        
        return topic, subtopic

    def _format_chat_history(self, chat_history: list[dict]) -> str:
        formatted_messages = []
        for message in chat_history:
            role = message.get('role', 'unknown')
            content = message.get('content', '')
            formatted_messages.append(f"Role: {role}, Content: {content}")
        return "\n".join(formatted_messages)
            
    async def randomfact_task(self):
        conversation_director_function_schema = self.config.function_schemas['conversationdirector']
        while True:
            await adjustable_sleep_task.adjustable_sleep_task(self.config, 'randomfact_sleeptime')

            # Prompt set in os.env on .bat file run
            selected_prompt = self.config.randomfact_prompt
            assistant_name = 'random_fact'
            thread_name = 'chatformemsgs'
            tts_voice = self.config.tts_voice_randomfact

            # Correctly pass the topics data structure to _pick_random_category and set a random character (used for 'fact' responses)
            topic, subtopic = self._pick_random_category(data=self.config.randomfact_topics)
            area, subarea = self._pick_random_category(data=self.config.randomfact_areas)
            random_character_a_to_z = random.choice('abcdefghijklmnopqrstuvwxyz')

            self.logger.debug(f"Selected topic: {topic}, Selected subtopic: {subtopic}")
            self.logger.debug(f"Selected area: {area}, Selected subarea: {subarea}")
            self.logger.debug(f"Selected random_character_a_to_z: {random_character_a_to_z}")
            self.logger.debug(f"Selected random voice: {tts_voice}")

            # Execute the function call and handle exceptions gracefully
            try:
                response_data, response = await self.gpt_function_call_manager.execute_function_call(
                    thread_name=thread_name, 
                    assistant_name='conversationdirector',
                    function_schema=conversation_director_function_schema
                    )
                response_type_result = response_data.get('response_type', 'fact')

            except Exception as e:
                self.logger.warning(f"Error occurred in 'randomfact_task'. Defaulting to 'fact': {e}")
                response_type_result = 'fact'

            # Set the prompt based on the response type
            if response_type_result == 'respond':
                selected_prompt = self.config.randomfact_response
            else:
                selected_prompt = self.config.randomfact_prompt
                task = AddMessageTask(
                    thread_name=thread_name,
                    message_role='user',
                    content='''No conversation happening here. Your next set of instructions will 
                    be to share a fact. Do so as instructed without acknowledging this message'''
                )
                await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="AddMessageTask 'randomfact_task'")

            self.logger.debug(f"selected_prompt: {selected_prompt[0:50]}")
            replacements_dict = {
                "wordcount_short":self.config.wordcount_short,
                'twitch_bot_display_name':self.config.twitch_bot_display_name,
                'randomfact_topic':topic,
                'randomfact_subtopic':subtopic,
                'area':area,
                'subarea':subarea,
                'random_character_a_to_z':random_character_a_to_z,
                'selected_game':self.config.randomfact_selected_game,
                'param_in_text':'variable_from_scope'
                }
            self.logger.debug(f"Replacements dict: {replacements_dict}")
            
            # Add a executeTask to the queue
            task = CreateExecuteThreadTask(
                thread_name=thread_name,
                assistant_name=assistant_name,
                thread_instructions=selected_prompt,
                replacements_dict=replacements_dict,
                tts_voice=tts_voice
            )
            await self.task_manager.add_task_to_queue_and_execute(thread_name, task, description="ExecuteThreadTask 'randomfact_task'")