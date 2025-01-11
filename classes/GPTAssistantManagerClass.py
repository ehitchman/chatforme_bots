import asyncio
import json

from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed
from collections import defaultdict
from typing import Dict, List, Callable
import requests

from my_modules.my_logging import create_logger

from classes.ConfigManagerClass import ConfigManager

from my_modules import utils

gpt_base_debug_level = 'INFO'
gpt_thread_mgr_debug_level = 'INFO'
gpt_assistant_mgr_debug_level = 'DEBUG'
gpt_response_mgr_debug_level = 'INFO'

class GPTBaseClass:
    """
    Initializes the GPT Base Class.

    Args:
        gpt_client: An instance of the OpenAI client.

    Attributes:
        logger (Logger): A logger for this class.
        gpt_client: The OpenAI client instance.
    """
    def __init__(self, gpt_client):
        self.logger = create_logger(
            dirname='log', 
            debug_level=gpt_base_debug_level,
            logger_name='GPTBaseClass',
            stream_logs=True
            )
        self.gpt_client = gpt_client
        self.yaml_data = ConfigManager.get_instance()

        def create():
            print("did a create")
        def delete():
            print("did a delete")

    def get_models(self) -> dict:
        url = 'https://api.openai.com/v1/models'
        headers = {'Authorization': f'Bearer {self.yaml_data.openai_api_key}'}

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch models: {e}")
            return {}

class GPTFunctionCallManager(GPTBaseClass):
    """
    Manages function calling with GPT Assistants, including creating an assistant,
    handling function calls, and submitting tool outputs.
    """

    def __init__(self, gpt_client, gpt_thread_manager, gpt_response_manager, gpt_assistant_manager):
        super().__init__(gpt_client)
        self.logger = create_logger(
            dirname='log',
            debug_level='INFO',
            logger_name='GPTFunctionCallManager',
            stream_logs=True
        )
        self.gpt_thread_manager = gpt_thread_manager
        self.gpt_response_manager = gpt_response_manager
        self.gpt_assistant_manager = gpt_assistant_manager

        # Initialize thread-specific locks
        self.thread_run_locks = defaultdict(asyncio.Lock)

    async def execute_function_call(
            self,
            thread_name: str, 
            assistant_name: str, 
            function_schema: json, 
            get_response=False
            ):
        """
        Executes the function call workflow for the specified thread.

        Returns:
            str: The final response from the assistant and the output data.
        """

        self.logger.info('Threads and Assistants:')
        self.logger.info(f"...Threads: {self.gpt_thread_manager.threads}")
        self.logger.info(f"...Assistants: {self.gpt_assistant_manager.assistants}")

        # Retrieve the thread/assistant ID by name
        try:
            assistant_entry = self.gpt_assistant_manager.assistants.get(assistant_name)
            assistant_id = assistant_entry['id']
        except KeyError:
            self.logger.error(f"...Assistant or id for '{assistant_name}' not found", exc_info=True)

        try:
            self.logger.info(f"Executing function call for thread '{thread_name}' with assistant '{assistant_name}'")
            thread_id = self.gpt_thread_manager.threads[thread_name]['id']
        except KeyError:
            self.logger.error("...thread name or id not found", exc_info=True)
        
        if not assistant_entry:
            self.logger.error(f"...Assistant '{assistant_name}' not found.")
        if not thread_id:
            self.logger.error(f"...Thread '{thread_name}' not found.")
        if not assistant_id:
            self.logger.error(f"...Assistant ID not found for '{assistant_name}'.")

        async with self.thread_run_locks[thread_name]:
            try:
                self.logger.info(f"...Starting run for thread '{thread_name}' with assistant '{assistant_id}'")

                # Check if there's an active run for this thread
                runs = self.gpt_client.beta.threads.runs.list(thread_id=thread_id)
                active_runs = [run for run in runs.data if run.status in ['queued', 'in_progress']]

                if active_runs:
                    active_run = active_runs[0]
                    self.logger.warning(f"...Thread '{thread_name}' already has an active run: {active_run.id}. Waiting for it to complete.")
                    await self._wait_for_run_completion(thread_id, active_run.id)

                # Start the new run
                wrapped_function_schema = [function_schema]
                run = self.gpt_client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tools = wrapped_function_schema
                )

            except Exception as e:
                self.logger.error(f"...Error starting run for thread '{thread_name}': {e}")

            try:
                # Poll the run status manually until it's complete
                while run.status in ['queued', 'in_progress']:
                    await asyncio.sleep(2)
                    run = self.gpt_client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run.id
                    )
            except Exception as e:
                self.logger.error(f"...Error polling run status for thread '{thread_name}': {e}")


                # Chedck if status is not in one of the all run states and log the status
                if run.status not in ['queued', 'in_progress', 'completed', 'failed', 'requires_action']:
                    self.logger.warning(f"...Run status is not in one of the expected states: {run.status}")
                else:
                    self.logger.debug(f"...Run created with status: {run.status}")

            try:
                # Check if the run completed and then handle the response
                if run.status == 'completed':
                    messages = self.gpt_client.beta.threads.messages.list(thread_id=thread_id)
                    final_response = self._extract_latest_response_from_thread_messages(messages)
                    self.logger.info(f"...Status is completed. Final response: {final_response}")
                    self.logger.info(f"...Final response: {final_response}")
                    self.logger.info(f"...Output data: {run.output_data}")
                    return None, final_response

                # Check if the run failed
                if run.status == 'failed':
                    error_details = run.last_error
                    self.logger.error(f"...Run failed with error: {error_details}")
                    raise RuntimeError(f"...Run failed: {error_details}")

                # Handle function calls if the run requires action
                if run.status == 'requires_action':

                    # Handle the required action and get the final response
                    tool_outputs, output_data = await self._handle_required_action(run)
                    self.logger.info(f"...Tool outputs: {tool_outputs}")

                    if get_response:
                        # Submit the tool outputs and wait for the run to complete
                        run = await self._submit_tool_outputs(thread_id, run.id, tool_outputs)

                        messages = self.gpt_client.beta.threads.messages.list(thread_id=thread_id)
                        final_response = self._extract_latest_response_from_thread_messages(messages)
                        self.logger.info(f"...Final response (get_response is {get_response}): {final_response}")

                    else:
                        run = await self._cancel_run(thread_id, run.id) 
                        final_response = None
                    
                self.logger.info(f"...Output data: {output_data}")
                self.logger.info(f"...Final response: {final_response}")
                return output_data, final_response
            
            except Exception as e:
                self.logger.error(f"Error handling function call: {e}")

    async def _wait_for_run_completion(self, thread_id, run_id):
        """Waits for a specific run to complete."""
        try:
            while True:
                run = self.gpt_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
                if run.status not in ['queued', 'in_progress']:
                    self.logger.info(f"Run {run_id} completed with status: {run.status}")
                    break
                await asyncio.sleep(1)
        except Exception as e:
            self.logger.error(f"Error waiting for run {run_id} to complete: {e}")
            raise

    async def _handle_required_action(self, run) -> tuple:
        """
        Handles the required action by extracting tool calls and preparing tool outputs.

        Args:
            run: The run object in 'requires_action' status.

        Returns:
            list: A list of tool outputs to submit.
        """
        tool_outputs = []

        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            function_name = tool_call.function.name
            arguments = tool_call.function.arguments

            # Check if arguments is a valid JSON string
            is_valid, parsed_arguments = self._is_valid_json(arguments)
            if not is_valid:
                self.logger.error(f"Invalid JSON arguments: {arguments}")
                continue

            # For this function, convert the output to a JSON string
            if function_name == "conversationdirector":
                output_data = {
                    "response_type": parsed_arguments.get("response_type"),
                    "reasoning": parsed_arguments.get("reasoning")
                }

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(output_data)
                })

        self.logger.info(f"Prepared tool outputs: {tool_outputs}")
        return tool_outputs, output_data
    
    async def _cancel_run(self, thread_id, run_id):
        """Cancels a specific run."""
        try:
            self.gpt_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run_id)
            self.logger.info(f"Run {run_id} cancelled successfully.")
        except Exception as e:
            self.logger.error(f"Error cancelling run {run_id}: {e}")
            raise

    async def _submit_tool_outputs(self, thread_id, run_id, tool_outputs):
        """
        Submits the tool outputs to the API and waits for completion.

        Args:
            thread_id (str): The thread ID.
            run_id (str): The run ID.
            tool_outputs (list): The tool outputs to submit.

        Returns:
            The updated run object.
        """
        try:
            # Submit the tool outputs
            run = self.gpt_client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run_id,
                tool_outputs=tool_outputs
            )
            self.logger.info("Tool outputs submitted successfully.")

            # Poll the status of the run
            while run.status in ['queued', 'in_progress', 'requires_action']:
                self.logger.info(f"Run status not completed: {run.status}")
                await asyncio.sleep(1)
                run = self.gpt_client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run_id
                )

            self.logger.info(f"Run completed with status: {run.status}")
            return run

        except Exception as e:
            self.logger.error(f"Failed to submit tool outputs: {e}")
            raise

    def _extract_latest_response_from_thread_messages(self, response_thread_messages):
        """
        Extracts the latest response from the thread messages.

        Args:
            response_thread_messages (list): A list of messages from a thread.

        Returns:
            The latest response message from the assistant, or None if no response is found.
        """
        try:
            sorted_messages = sorted(response_thread_messages.data, key=lambda msg: msg.created_at, reverse=True)

            for message in sorted_messages:
                if message.role == 'assistant':
                    for content in message.content:
                        if content.type == 'text':
                            return content.text.value

            self.logger.warning("No response found in thread messages.")
            return None

        except Exception as e:
            self.logger.error(f"Error extracting response: {e}")
            raise

    def _is_valid_json(self, data):
        """
        Checks if the provided data is a valid JSON string.

        Args:
            data (str): The string to check.

        Returns:
            tuple: (bool, dict or list or None). True and the parsed JSON if valid, False and None otherwise.
        """
        if not isinstance(data, str):
            return False, None

        try:
            parsed_data = json.loads(data)
            return True, parsed_data
        except json.JSONDecodeError as e:
            return False, None
                
class GPTAssistantManager(GPTBaseClass):
    """
    Initializes the GPT Assistant Manager.

    Args:
        yaml_data: Configuration data loaded from a YAML file.
        gpt_client: An instance of the OpenAI client.

    Attributes:
        logger (Logger): A logger for this class.
        yaml_data (dict): Configuration data extracted from yaml_data.
        gpt_client: The OpenAI client instance.
        assistants (dict): A dictionary to store assistant objects and their IDs.
    """
    def __init__(self, gpt_client):
        super().__init__(gpt_client)
        self.logger = create_logger(
            dirname='log', 
            debug_level=gpt_assistant_mgr_debug_level,
            logger_name='GPTAssistantManager',
            stream_logs=True
            )
        self.assistants = {}

    def _create_assistant(
            self, 
            assistant_name, 
            assistant_instructions="you're a question answering machine", 
            replacements_dict: dict=None,
            assistant_type=None, 
            assistant_model=None
            ):
        """
        Creates an assistant with the specified parameters.

        Args:
            assistant_name (str): The name of the assistant to create. Default is 'default'.
            assistant_instructions (str): Instructions for the assistant. Default is a generic instruction.
            assistant_type: The type of the assistant. Defaults to the type specified in the configuration.
            assistant_model: The model of the assistant. Defaults to the model specified in the configuration.

        Returns:
            The created assistant object.
        """
        assistant_type = assistant_type or self.yaml_data.gpt_assistant_type
        assistant_model = assistant_model or self.yaml_data.gpt_model
        assistant_instructions = utils.populate_placeholders(
            logger=self.logger,
            prompt_template=assistant_instructions,
            replacements=replacements_dict
            )
        
        assistant = self.gpt_client.beta.assistants.create(
            name=assistant_name,
            instructions=assistant_instructions,
            tools=[{"type": assistant_type}],
            model=assistant_model
        )
        self.assistants[assistant_name] = {'object':assistant, 'id':assistant.id}

        self.logger.info(f"Assistant object created successfully for '{assistant_name}' with instructions: {assistant_instructions[0:75]}...")
        self.logger.debug(assistant)
        return assistant

    def create_assistants(self, assistants_config: dict) -> dict:
        # Create Assistants
        replacements_dict = {
            "wordcount_short":self.yaml_data.wordcount_short,
            "wordcount_medium":self.yaml_data.wordcount_medium,
            "wordcount_long":self.yaml_data.wordcount_long,
            "vibecheckee_username": 'chad',
            "vibecheck_message_wordcount": self.yaml_data.vibechecker_message_wordcount,
        }

        self.logger.info('Creating GPT Assistants')

        # Get suffix one from assistants_config
        gpt_assistants_suffix = self.yaml_data.gpt_assistants_suffix

        for assistant_name, prompt in assistants_config.items():
            final_prompt = prompt + gpt_assistants_suffix
            self._create_assistant(
                assistant_name=assistant_name,
                assistant_instructions=final_prompt,
                replacements_dict=replacements_dict,
                assistant_type='code_interpreter',
                assistant_model=self.yaml_data.gpt_model
            )        
        return self.assistants

    def _create_assistant_with_function(self, assistant_name, instructions, function_schema):
        """
        Creates an assistant with the get_bot_response function schema.
        """
        tool = [function_schema]
        assistant = self.gpt_client.beta.assistants.create(
            name=assistant_name,
            instructions=instructions,
            tools=tool,
            model=self.yaml_data.gpt_model
        )

        self.assistants[assistant_name] = {'object': assistant, 'id': assistant.id}
        self.logger.info(f"Assistant '{assistant_name}' created with ID: {assistant.id}")

    def create_assistants_with_functions(self, assistants_with_functions: list):
        """
        Creates multiple assistants with their respective function schemas.

        Args:
            assistants_with_functions (list): A list of dictionaries, each containing
                                            'name', 'instructions', and 'json_schema'.
        Returns:
            dict: A dictionary of created assistants with their names and IDs.
        """
        self.logger.info('Creating GPT Assistants with functions')

        for assistant_details in assistants_with_functions:
            name = assistant_details["name"]
            instructions = assistant_details["instructions"]
            json_schema = assistant_details["json_schema"]
            self.logger.debug(f'Creating assistant with function: {name}')
            self.logger.debug(f'Instructions: {instructions}')
            self.logger.debug(f"Json Schema Type: {type(json_schema)}")
            self.logger.debug(f'JSON Schema: {json_schema}')

            try:
                self._create_assistant_with_function(
                    assistant_name=name,
                    instructions=instructions,
                    function_schema=json_schema
                )
                self.logger.info(f"Assistant '{name}' created successfully.")
            except Exception as e:
                self.logger.error(f"Error creating assistant '{name}': {e}")

        self.logger.info(f"Current assistants: {list(self.assistants.keys())}")
        return self.assistants

class GPTThreadManager(GPTBaseClass):
    def __init__(self, gpt_client):
        super().__init__(gpt_client=gpt_client)
        self.logger = create_logger(
            dirname='log', 
            debug_level=gpt_thread_mgr_debug_level,
            logger_name='GPTThreadManager',
            stream_logs=True
        )

        # Initialize the 'threads' dictionary to store thread objects and their IDs
        self.threads: Dict[str, dict] = {}

    def _create_thread(self, thread_name: str):
        """
        Creates a new thread with the given name.

        Args:
            thread_name (str): The name of the thread to be created.

        Returns:
            The created thread object.
        """
        # Store the thread object and its ID in the 'threads' dictionary using 'thread_name' as the key
        thread = self.gpt_client.beta.threads.create()
        self.threads[thread_name] = {'id': thread.id}

        self.logger.info(f"Created thread '{thread_name}' with ID: {thread.id}")

    def create_threads(self, thread_names):
        self.logger.info('Creating GPT Threads')
        for thread_name in thread_names:

            #NOTE: Part of 'reusing threads' logic
            #If thread does not exist, create it
            if thread_name not in self.threads:
                self._create_thread(thread_name)
            else:
                self.logger.warning(f"Thread '{thread_name}' already exists")

        self.logger.info(f"...threads created: {self.threads}")        
        return self.threads

class GPTResponseManager(GPTBaseClass):
    """
    Initializes the GPT Assistant Response Manager.

    Args:
        gpt_client: An instance of the OpenAI client.

    Attributes:
        logger (Logger): A logger for this class.
        gpt_client: The OpenAI client instance.
        yaml_data: Configuration data loaded from a YAML file.
    """
    def __init__(self, gpt_client, gpt_thread_manager, gpt_assistant_manager, max_waittime_for_gpt_response=120):
        super().__init__(gpt_client=gpt_client)
        self.logger = create_logger(
            dirname='log', 
            debug_level=gpt_response_mgr_debug_level,
            logger_name='GPTResponseManager',
            stream_logs=True
            )
        self.gpt_thread_manager = gpt_thread_manager
        self.gpt_assistant_manager = gpt_assistant_manager
        self.max_waittime_for_gpt_response = max_waittime_for_gpt_response

    async def _get_response(self, thread_id, run_id, polling_seconds=3):
        """
        Asynchronously retrieves the response for a given thread and run ID.
        """
        counter = 1
        while counter < self.max_waittime_for_gpt_response:
            response = self.gpt_client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id
            )
            if response.status == 'completed':
                self.logger.debug("This is the completed 'response' object:")
                self.logger.debug(response)
                return response
            else:
                elapsed_time = counter * polling_seconds
                self.logger.info(f"The 'response' object is not completed yet. Polling time: {elapsed_time} seconds...")
                counter += 1
            await asyncio.sleep(polling_seconds)

        raise ValueError(f"Response not completed after {counter * polling_seconds} seconds")

    async def _run_and_get_assistant_response_thread_messages(
            self, 
            thread_id: str, 
            assistant_id: str,
            thread_instructions:str='Answer the question using clear and concise language',
            replacements_dict:dict=None
            ):
        """
        Asynchronously runs the assistant on a specified thread and retrieves the thread messages.

        Args:
            thread_id (str): The ID of the thread on which the assistant is run.
            assistant_id (str): The ID of the assistant to be run on the thread.
            thread_instructions (str): Instructions for the assistant. Defaults to a generic instruction.

        Returns:
            A list of response thread messages.
        """
        try:
            final_thread_instructions = utils.populate_placeholders(
                logger=self.logger,
                prompt_template=thread_instructions,
                replacements=replacements_dict
                )
            self.logger.debug(f"This is the final thread_instructions: {final_thread_instructions}")
        except Exception as e:
            self.logger.error(f"Error replacing prompt text with replacements_dict")
            self.logger.error(e)
            raise ValueError(f"Error replacing prompt text with replacements_dict")   
        
        try:
            run = self.gpt_client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id,
                instructions=final_thread_instructions
            )
            self.logger.debug("This is the 'run' object:")
            self.logger.debug(run)
        except Exception as e:
            self.logger.error(f"Error running assistant on thread")
            self.logger.error(e)
            raise ValueError(f"Error running assistant on thread")
        
        await self._get_response(thread_id, run.id)
        response_thread_messages = self.gpt_client.beta.threads.messages.list(thread_id=thread_id)

        self.logger.debug("This is the 'messages' object response_thread_messages:")
        self.logger.debug(response_thread_messages)
        return response_thread_messages
    
    def _extract_latest_response_from_thread_messages(self, response_thread_messages):
        """
        Extracts the latest response from the thread messages.

        Args:
            response_thread_messages (list): A list of messages from a thread.

        Returns:
            The latest response message from the assistant, or None if no response is found.
        """
        try:
            sorted_response_thread_messages = sorted(response_thread_messages.data, key=lambda msg: msg.created_at, reverse=True)
            self.logger.debug("...This is the sorted_response_thread_messages:")
            self.logger.debug(sorted_response_thread_messages)

            for message in sorted_response_thread_messages:
                self.logger.debug(f"...This is the message.role: {message.role}")
                if message.role == 'assistant':
                    for content in message.content:
                        if content.type == 'text':
                            self.logger.info(f"Scheduler-4: This is the gpt response from the '{message.role}': {content.text.value}")
                            return content.text.value
                else:
                    self.logger.error("...No response found in thread messages")
                    raise ValueError("...No response found in thread messages")    
            return None
        except Exception as e:
            self.logger.error(f"...Error extracting latest response from thread messages")
            self.logger.error(e)
            raise ValueError(f"...Error extracting latest response from thread messages")
        
    async def execute_thread(
        self, 
        assistant_name: str, 
        thread_name: str, 
        thread_instructions: str, 
        replacements_dict=None
        ) -> str:
        """
        Executes the workflow to get the GPT assistant's response to a thread.

        Args:
            assistant_id (str): The ID of the assistant.
            thread_id (str): The ID of the thread.
            thread_instructions (str): Instructions for the assistant.

        Returns:
            The final response message from the assistant.
        """
        assistant_id = self.gpt_assistant_manager.assistants[assistant_name]['id']
        thread_id = self.gpt_thread_manager.threads[thread_name]['id']
        self.logger.info(f"Scheduler-3: Executing Assistant/Thread: '{assistant_name}' ({assistant_id}, Thread id: {thread_id}")
        self.logger.info(f"...Thread_instructions: {thread_instructions[0:50]}...")

        try:
            response_thread_messages = await self._run_and_get_assistant_response_thread_messages(
                assistant_id=assistant_id,
                thread_id=thread_id,
                thread_instructions=thread_instructions,
                replacements_dict=replacements_dict
            )        
            extracted_message = self._extract_latest_response_from_thread_messages(response_thread_messages)
            self.logger.debug(f"...Extracted message and length: ({len(extracted_message)}) Message: {extracted_message}")
        except Exception as e:
            self.logger.error(f"...Error running assistant on thread: {e}")
            raise ValueError(f"...Error running assistant on thread: {e}")
        
        #Check length of output
        if len(extracted_message) > self.yaml_data.assistant_response_max_length:
            self.logger.warning(f"...Message exceeded character length ({self.yaml_data.assistant_response_max_length}), processing the gpt thread again")
            self.logger.debug(f"...This is the shorten_response_length_prompt: {self.yaml_data.shorten_response_length_prompt}")
            
            # Add {message_to_shorten} to replacements_dict
            replacements_dict['message_to_shorten'] = extracted_message
            replacements_dict['original_thread_instructions'] = thread_instructions

            try:
                response_thread_messages = await self._run_and_get_assistant_response_thread_messages(
                    assistant_id=assistant_id,
                    thread_id=thread_id,
                    thread_instructions=self.yaml_data.shorten_response_length_prompt,
                    replacements_dict=replacements_dict
                )
            except Exception as e:
                self.logger.error(f"...Error running assistant on thread")
                self.logger.error(e)
                raise ValueError(f"...Error running assistant on thread")
                        
            # Extract the latest response from the messages
            extracted_message = self._extract_latest_response_from_thread_messages(response_thread_messages)

        self.logger.debug("...This is the response_thread_messages object:")
        self.logger.debug(response_thread_messages)
        self.logger.info(f"...This is the final response from execute_thread(): '{extracted_message}'")
        return extracted_message

    async def add_message_to_thread(
            self, 
            message_content: str, 
            thread_name: str, 
            role='user'
            ) -> object:
        """
        Asynchronously adds a message to a specified thread identified by its name, using the OpenAI GPT Assistants API.
        Retries the operation up to 3 times in case of failures, with a 1-second wait between retries.

        Args:
            message_content (str): The textual content of the message to be added to the thread.
            thread_name (str): The name of the thread to which the message will be added. The thread must be previously created and registered.
            role (str): Specifies the role of the entity sending the message. Must be either 'user' or 'assistant'.
                        The default role is 'user'.

        Returns:
            The response object representing the created message, or None if the specified thread does not exist or if the message could not be added after retries.

        Raises:
            ValueError: If the 'role' parameter is not 'user' or 'assistant'.
        """
        #NOTE: could use a thread registry to share self.threads between classes 
        self.logger.debug(f"Message content (role: {role}, thread_name: {thread_name}): {message_content[0:50]}...")
        
        # Validate the role
        if role not in ['user', 'assistant']:
            raise ValueError(f"Invalid role: {role}. Role must be 'user' or 'assistant'.")

        if thread_name in self.gpt_thread_manager.threads:
            thread_id = self.gpt_thread_manager.threads[thread_name]['id']

            async for attempt in AsyncRetrying(stop=stop_after_attempt(3), wait=wait_fixed(1), reraise=True):
                with attempt:
                    message_object = self.gpt_client.beta.threads.messages.create(
                        thread_id=thread_id, 
                        role=role, 
                        content=message_content
                    )
                    self.logger.info(f"... added message to thread ({thread_name}/{thread_id}): Message content {message_content[0:50]}...")
                    return message_object
        else:
            self.logger.warning(f"Thread '{thread_name}' not found.")
            return None

async def main():
    import openai
    import os

    os.environ['CHATZILLA_CONFIG_DIRPATH'] = r'C:\_repos\chatzilla_ai\config'
    os.environ['CHATZILLA_YAML_FILE'] = 'chatzilla_ai_ehitch.yaml'
    os.environ['CHATZILLA_ENV_FILENAME'] = '.env'
    os.environ['CHATZILLA_KEYS_ENV_DIRPATH'] = 'keys'
    os.environ['CHATZILLA_KEYS_ENV_FILENAME'] = '.env.keys'
    os.environ['CHATZILLA_YAML_PATH'] = r'.\config\bot_user_configs' '\\' + os.getenv('CHATZILLA_YAML_FILE')
    
    #yaml_filepath = r'C:\_repos\chatzilla_ai\config\bot_user_configs\chatzilla_ai_ehitch.yaml'
    print(f"yaml_filepath_type: {type(os.environ['CHATZILLA_YAML_PATH'])}")

    ConfigManager.initialize(yaml_filepath=os.environ['CHATZILLA_YAML_PATH'])
    config = ConfigManager.get_instance()

    # openai client
    gpt_client = openai.OpenAI(api_key = config.openai_api_key)

    # Initialize the thread manager and assistant manager and response manager
    assistant_manager = GPTAssistantManager(gpt_client)
    thread_manager = GPTThreadManager(gpt_client)
    response_manager = GPTResponseManager(gpt_client, thread_manager, assistant_manager)
    function_call_manager = GPTFunctionCallManager(gpt_client, thread_manager, response_manager, assistant_manager)

    # ######################################
    # # TEST 1: Add messages to the thread
    # # Add some messages to the thread that imitate a Twitch stream conversation
    # messages = [
    #     {"role": "user", "content": "Hey everyone, what's up?"},
    #     {"role": "user", "content": "Did you guys see that epic fail earlier? 😂"},
    #     {"role": "user", "content": "Can anyone explain how the scoring works in this game?"},
    #     {"role": "user", "content": "yeah it's 1 and then 2 and then 3 and so on..."},
    #     {"role": "user", "content": "This stream is awesome, love the community here!"},
    #     {"role": "user", "content": "What do you think bot!"},
    # ]

    # # Add messages to the thread
    # for msg in messages:
    #     await response_manager.add_message_to_thread(
    #         message_content=msg["content"],
    #         thread_name=thread_name,
    #         role=msg["role"]
    #     )
    # print("Messages added to the thread.")

    # ######################################
    # # TEST 2: Execute the function call on the thread and get the assistant's response
    # # Execute the function call on the thread and get the assistant's response
    # output_data, response = await function_call_manager.execute_function_call(thread_name, assistant_name='conversationdirector')
    
    # # Print out the messages from the thread
    # thread_id = thread_manager.threads[thread_name]['id']
    # messages = gpt_client.beta.threads.messages.list(thread_id=thread_id)
    # print("Messages in the thread:")
    # for message in messages.data:     
    #     print(f"Message: {message.content[0].text.value} ({message.role})")

    # # Print the final response from the assistant
    # print(f"output_data: {output_data}")
    # print(f"Assistant's Response: {response}")

    ######################################
    # TEST 3: Now try to create_assistants and threads
    assistant_manager.create_assistants(config.gpt_assistants_config)
    assistant_manager.create_assistants_with_functions(config.gpt_assistants_with_functions_config)

    thread_manager.create_threads(config.gpt_thread_names)

    ######################################
    # TEST 4 (requires TEST#3): Try to use function call manager to execute a function call
    thread_name = "chatformemsgs"
    assistant_name = "conversationdirector"
    conversation_director_function_schema = config.function_schemas['conversationdirector']
    output_data, response = await function_call_manager.execute_function_call(
        thread_name, 
        assistant_name, 
        function_schema=conversation_director_function_schema,
        get_response=False
        )
    print(f"output_data: {output_data}")
    print(f"Assistant's Response: {response}")

# Run the async main function
if __name__ == "__main__":
    asyncio.run(main())