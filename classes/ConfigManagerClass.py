import os
import yaml
import dotenv
import json

# from my_modules.my_logging import create_logger
from my_modules import my_logging
from my_modules import utils

runtime_logger_level = 'INFO'

class ConfigManager:
    _instance = None

    @classmethod
    def initialize(cls, yaml_filepath):

        #full path to the yaml file
        cls.abs_yaml_filepath = os.path.abspath(yaml_filepath)

        # Set environment variables
        cls.app_config_dirpath = os.getenv('CHATZILLA_CONFIG_DIRPATH')
        cls.env_filename = os.getenv('CHATZILLA_ENV_FILENAME')
        cls.abs_env_filepath = os.getenv('CHATZILLA_CONFIG_DIRPATH') + '\\' + os.getenv('CHATZILLA_ENV_FILENAME')

        if cls._instance is None:
            try:
                cls._instance = object.__new__(cls)
            except Exception as e:
                print(f"Exception in object.__new__(cls): {e}")
            
            try:
                cls._instance.create_logger()
            except Exception as e:
                print(f"Exception in create_logger(): {e}")

            try:
                cls._instance.initialize_config(yaml_filepath=cls.abs_yaml_filepath)
            except Exception as e:
                print(f"Exception in initialize_config(): {e}")

    @classmethod
    def get_instance(cls):
        try:
            if cls._instance is None:
                raise Exception("ConfigManager is not initialized. Call 'initialize' first.")
            return cls._instance
        except Exception as e:
            print(f"Exception in get_instance(): {e}")

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
        else:
            raise Exception("You cannot create multiple instances of ConfigManager. Use 'get_instance'.")

    def initialize_config(self, yaml_filepath):
        # Set environment variables from .env and .env.keys files
        try:
            self.set_env_file_variables()
        except Exception as e:
            self.logger.error(f"Error, exception in set_env_file_variables(): {e}", exc_info=True)

        # Get YAML configurations
        try:
            self.load_yaml_config(yaml_full_path=yaml_filepath)
        except Exception as e:
            self.logger.error(f"Error, exception in load_yaml_config(): {e}", exc_info=True)

        # Log the configuration
        try:
            self._log_config()
        except Exception as e:
            self.logger.error(f"Error, exception in log_config(): {e}", exc_info=True)
                              
    def load_yaml_config(self, yaml_full_path):
        try:
            with open(yaml_full_path, 'r') as file:
                self.logger.debug("loading individual configs...")
                self.yaml_data = yaml.safe_load(file)
        except FileNotFoundError as e:
            self.logger.error(f"FileNotFoundError in load_yaml_config(): {e}")
            raise
        except yaml.YAMLError as e:
            self.logger.error(f"yaml.YAMLError in load_yaml_config(): {e}")
            raise
        except Exception as e:
            self.logger.error(f"Exception in load_yaml_config(): {e}")
            raise

        # This happens first because we need to update the config from the YAML file before proceeding
        try:
            self.update_config_from_yaml(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in update_config_from_yaml(): {e}")
            raise
        
        # The rest can happen mostly in any order
        try:
            self.yaml_twitchbot_config(self.yaml_data) 
        except Exception as e:
            self.logger.error(f"Error in yaml_twitchbot_config(): {e}")
            raise

        try:
            self.yaml_depinjector_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_depinjector_config(): {e}")
            raise

        try:
            self.update_spellcheck_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in update_spellcheck_config(): {e}")
            raise

        try:
            self.yaml_gcp_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gcp_config(): {e}")
            raise

        try:       
            self.yaml_botears_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_botears_config(): {e}")
            raise

        try:
            self.yaml_gpt_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_config(): {e}")
            raise

        try:
            self.yaml_gpt_voice_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_voice_config(): {e}")
            raise

        try:
            self.yaml_gpt_explain_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_explain_config(): {e}")      
            raise

        try:
            self.yaml_gpt_thread_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_thread_config(): {e}")
            raise

        try:
            self.yaml_gpt_assistant_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_assistant_config(): {e}")
            raise

        try:
            self.yaml_chatforme_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_chatforme_config(): {e}")
            raise

        try:
            self.yaml_ouat_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_ouat_config(): {e}")
            raise

        try:
            self.yaml_vibecheck_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_vibecheck_config(): {e}")
            raise
        
        try:
            self.yaml_helloworld_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_helloworld_config(): {e}")
            raise

        try:
            self.yaml_gpt_assistants_with_functions_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_assistants_with_functions_config(): {e}")
            raise

        try:
            self.yaml_factchecker_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_factchecker_config(): {e}")
            raise

        try:
            self.yaml_tts_config(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_tts_config(): {e}")
            raise

        try:
            self.yaml_randomfact_json(self.yaml_data)
        except Exception as e:
            self.logger.error(f"Error in yaml_randomfact_json(): {e}")
            raise

    def set_env_file_variables(self):
        '''Loads environment variables from a .env file.'''

        # Load environment variables set at runtime
        self._update_config_from_env_set_at_runtime()
                


        # Load environment variables from .env file
        if self.app_config_dirpath and self.env_filename:
            self.env_path = os.path.join(self.app_config_dirpath, self.env_filename)
            if os.path.exists(self.env_path):
                try:
                    dotenv.load_dotenv(self.env_path)
                except Exception as e:
                    self.logger.error(f"Error in set_env_file_variables() -> load_dotenv(self.env_path): {e}")
                try:
                    self._update_config_from_env()
                except Exception as e:
                    self.logger.error(f"Error in set_env_file_variables() -> _update_config_from_env(): {e}")
            else:
                self.logger.error(f".env file not found at {self.env_path}")
                
        # Load environment variables from .env.keys file
        if self.app_config_dirpath and self.abs_env_filepath and self.keys_env_filename and self.keys_env_dirpath:
            self.keys_env_path = os.path.join(self.app_config_dirpath, self.keys_env_dirpath, self.keys_env_filename)
            if os.path.exists(self.keys_env_path):
                try:
                    dotenv.load_dotenv(self.keys_env_path)
                except Exception as e:
                    self.logger.error(f"Error in set_env_file_variables() -> load_dotenv(self.keys_env_path): {e}")
                try:
                    self._update_config_from_env_keys()
                except Exception as e:
                    self.logger.error(f"Error in set_env_file_variables(): -> _update_config_from_env_keys(): {e}")
            else:
                self.logger.error(f".env file not found at {self.keys_env_path}")

    def _update_config_from_env_set_at_runtime(self):
        try:
            self.chatzilla_port_number = str(os.getenv("CHATZILLA_PORT_NUMBER"))
        except Exception as e:
            self.logger.error(f"Error in update_config_from_env_set_at_runtime(): {e}")

    def _update_config_from_env_keys(self):
        try:
            # OpenAI API
            self.openai_api_key = os.getenv('OPENAI_API_KEY')
            
            # Twitch API
            self.twitch_broadcaster_author_id = os.getenv('TWITCH_BROADCASTER_AUTHOR_ID')
            self.twitch_bot_client_id = os.getenv('TWITCH_BOT_CLIENT_ID')
            self.twitch_bot_client_secret = os.getenv('TWITCH_BOT_CLIENT_SECRET')

        except Exception as e:
            self.logger.error(f"Error in update_config_from_env(): {e}")

    def _update_config_from_env(self):
        try:
            # Environment & Keys

            self.keys_env_dirpath = os.getenv('CHATZILLA_KEYS_ENV_DIRPATH')
            self.keys_env_filename = os.getenv('CHATZILLA_KEYS_ENV_FILENAME')

            # Chatzilla related
            self.chatzilla_mic_device_name = os.getenv('CHATZILLA_MIC_DEVICE_NAME')

            # GCP Related
            self.google_service_account_credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE')
            self.talkzillaai_userdata_table_id = os.getenv('TALKZILLAAI_USERDATA_TABLE_ID')
            self.talkzillaai_usertransactions_table_id = os.getenv('TALKZILLAAI_USERTRANSACTIONS_TABLE_ID') 
        
        except Exception as e:
            self.logger.error(f"Error in update_config_from_env(): {e}")

    def yaml_tts_config(self, yaml_data):
        try:
            self.tts_include_voice = yaml_data['openai-api']['tts_include_voice']
        except Exception as e:
            self.logger.error(f"Error in yaml_tts_config(): {e}")

    def yaml_gcp_config(self, yaml_data):
        try:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.path.join(
                self.app_config_dirpath,
                self.keys_env_dirpath, 
                self.google_service_account_credentials_file
                )
        except Exception as e:
            self.logger.error(f"Error in yaml_gcp_config(): {e}\nTraceback:", exc_info=True)

    def yaml_botears_config(self, yaml_data):
        try:
            self.botears_prompt = yaml_data['botears_prompt']
            self.botears_audio_path = yaml_data['botears_audio_path']
            self.botears_audio_filename = yaml_data['botears_audio_filename']
            self.botears_save_length_seconds = yaml_data['botears_save_length_seconds']
            self.botears_buffer_length_seconds = yaml_data['botears_buffer_length_seconds']

        except Exception as e:
            self.logger.error(f"Error in yaml_botears_config(): {e}")

    def yaml_gpt_config(self, yaml_data):
        try:
            self.wordcount_short = str(yaml_data['chatbot_config']['wordcounts']['short']) #2024-06-09: shouldn't these be captured as ints and typecasted when used?
            self.wordcount_medium = str(yaml_data['chatbot_config']['wordcounts']['medium'])
            self.wordcount_long = str(yaml_data['chatbot_config']['wordcounts']['long'])
            self.magic_max_waittime_for_gpt_response = int(yaml_data['openai-api']['magic_max_waittime_for_gpt_response'])
        except Exception as e:
            self.logger.error(f"Error in yaml_gpt_config(): {e}")

    def yaml_gpt_assistant_config(self, yaml_data):
        self.gpt_assistants_config = yaml_data['gpt_assistants_config']
        self.assistant_response_max_length = yaml_data['openai-api']['assistant_response_max_length']
        self.gpt_assistants_suffix = yaml_data['gpt_assistants_suffix']

    def yaml_gpt_assistants_with_functions_config(self, yaml_data):
        """
        Dynamically loads assistants with their instructions and JSON configurations from the YAML file.

        Args:
            yaml_data (dict): The parsed YAML configuration.

        Returns:
            list: A list of dictionaries containing the name, instructions, and JSON data for each assistant.
        """

        self.gpt_assistants_with_functions_config = []

        # Load the function schemas from the JSON file
        gpt_assistants_with_functions_config = yaml_data.get('gpt_assistants_with_functions', {})
        self.function_schemas_path = gpt_assistants_with_functions_config['function_call_schema_file_path']
        
        self.function_schemas = utils.load_json(path_or_dir=self.function_schemas_path)
        assistants_dict = gpt_assistants_with_functions_config.get('assistants', {})

        self.logger.debug('The following assistants are being loaded with their instructions and JSON configurations:')
        self.logger.debug(f'function_schemas_path: {self.function_schemas_path}')
        self.logger.debug(f'function_schemas: {self.function_schemas}')
        self.logger.debug(f'assistants_dict: {assistants_dict}')
        
        for name, instructions in assistants_dict.items():
            instructions = instructions.get('instructions')
            function_schema = self.function_schemas[name]

            try:
                assistant_entry = {
                    "name": name,
                    "instructions": instructions,
                    "json_schema": function_schema
                }
                self.gpt_assistants_with_functions_config.append(assistant_entry)

            except Exception as e:
                self.logger.error(f"Error in yaml_gpt_assistants_with_functions_config(): {e}")

    def yaml_gpt_thread_config(self, yaml_data):
        self.gpt_thread_names = yaml_data['gpt_thread_names']

    def yaml_gpt_explain_config(self, yaml_data):
        self.gpt_explain_prompts = yaml_data['gpt_explain_prompts']
        self.explanation_suffix = yaml_data['gpt_explain_prompts']['explanation_suffix']
        self.explanation_starter = yaml_data['gpt_explain_prompts']['explanation_starter']
        self.explanation_progressor = yaml_data['gpt_explain_prompts']['explanation_progressor']
        self.explanation_additional_detail_addition = yaml_data['gpt_explain_prompts']['explanation_additional_detail_addition']
        self.explanation_user_opening_summary_prompt = yaml_data['gpt_explain_prompts']['explanation_user_opening_summary_prompt']
        self.explanation_ender = yaml_data['gpt_explain_prompts']['explanation_ender']

        self.explanation_progression_number = yaml_data['gpt_explain_prompts']['explanation_progression_number']
        self.explanation_max_counter_default = yaml_data['gpt_explain_prompts']['explanation_max_counter_default']
        self.explanation_message_recurrence_seconds = yaml_data['gpt_explain_prompts']['explanation_message_recurrence_seconds']

    def yaml_gpt_voice_config(self, yaml_data):
        self.openai_vars = yaml_data['openai-api']
        self.tts_voice_randomfact = yaml_data['openai-api']['tts_voice_randomfact']
        self.tts_voice_chatforme = yaml_data['openai-api']['tts_voice_chatforme']
        self.tts_voice_story = yaml_data['openai-api']['tts_voice_story']
        self.factcheck_voice = yaml_data['openai-api']['tts_voice_factcheck']
        self.tts_voice_newuser = yaml_data['openai-api']['tts_voice_newuser']
        self.tts_voice_default = yaml_data['openai-api']['tts_voice_default']
        self.tts_voice_vibecheck = yaml_data['openai-api']['tts_voice_vibecheck']

    def yaml_vibecheck_config(self, yaml_data):
        try:
            self.vibechecker_max_interaction_count = yaml_data['vibechecker_max_interaction_count']
            self.formatted_gpt_vibecheck_prompt = yaml_data['formatted_gpt_vibecheck_prompt']
            self.formatted_gpt_viberesult_prompt = yaml_data['formatted_gpt_viberesult_prompt']
            self.newusers_sleep_time = yaml_data['newusers_sleep_time']
            self.newusers_msg_prompt = yaml_data['newusers_msg_prompt']
            self.newusers_faiss_default_query = yaml_data['newusers_faiss_default_query']
            self.returningusers_msg_prompt = yaml_data['returningusers_msg_prompt']
            self.vibechecker_message_wordcount = str(yaml_data['vibechecker_message_wordcount'])
            self.vibechecker_question_session_sleep_time = yaml_data['vibechecker_question_session_sleep_time']
            self.vibechecker_listener_sleep_time = yaml_data['vibechecker_listener_sleep_time']
            self.formatted_gpt_vibecheck_alert = yaml_data['formatted_gpt_vibecheck_alert']
        except Exception as e:
            self.logger.error(f"Error in yaml_vibecheck_config(): {e}")

    def yaml_twitchbot_config(self, yaml_data):
        try:
            self.twitch_bot_gpt_hello_world = yaml_data['twitch-app']['twitch_bot_gpt_hello_world']
            self.twitch_bot_gpt_new_users_service = yaml_data['twitch-app']['twitch_bot_gpt_new_users_service']
            self.flag_returning_users_service = yaml_data['twitch-app']['twitch_bot_gpt_returning_users_faiss_service']

            self.twitch_bot_channel_name = yaml_data['twitch-app']['twitch_bot_channel_name']
            self.twitch_bot_username = yaml_data['twitch-app']['twitch_bot_username']
            self.twitch_bot_display_name = yaml_data['twitch-app']['twitch_bot_display_name']
            self.twitch_bot_moderators = yaml_data['twitch-app']['twitch_bot_moderators']
            self.num_bot_responses = yaml_data['chatforme_randomfacts']['num_bot_responses']
            self.twitch_bot_operatorname = yaml_data['twitch-app']['twitch_bot_operatorname']
            self.msg_history_limit = yaml_data['chatbot_config']['msg_history_limit']

        except Exception as e:
            self.logger.error(f"Error in yaml_twitchbot_config(): {e}")

    def yaml_chatforme_config(self, yaml_data):
        try:
            self.chatforme_prompt = yaml_data['chatforme_prompts']['standard']
        except Exception as e:
            self.logger.error(f"Error in yaml_chatforme_config(): {e}")

    def yaml_helloworld_config(self, yaml_data):
        try:
            self.gpt_hello_world = self.gpt_hello_world = True if os.getenv('gpt_hello_world') == 'True' else False
            self.hello_assistant_prompt = yaml_data['formatted_gpt_helloworld_prompt']
        except Exception as e:
            self.logger.error(f"Error in yaml_helloworld_config(): {e}")

    def yaml_ouat_config(self, yaml_data):

        def set_story_progression_number(max_counter):
            if max_counter < 5:
                progression_number = max_counter - 2
            else:
                progression_number = int(max_counter * 0.60)
            progression_number = max(1, min(progression_number, max_counter - 3))
            return progression_number
        
        def set_story_climax_number(max_counter, progression_number):
            if max_counter < 5:
                climax_number = max_counter - 1
            else:
                climax_number = int(max_counter * 0.75)
            climax_number = max(progression_number + 1, min(climax_number, max_counter - 2))
            return climax_number

        def set_story_finisher_number(max_counter, climax_number):
            if max_counter < 5:
                finisher_number = max_counter - 1
            else:
                finisher_number = int(max_counter * 0.90)
            finisher_number = max(climax_number + 1, min(finisher_number, max_counter - 1))
            return finisher_number
    
        try:
            # News Article Feed/Prompts
            self.newsarticle_rss_feed = yaml_data['ouat_storyteller']['newsarticle_rss_feed']
            self.story_article_bullet_list_summary_prompt = yaml_data['gpt_thread_prompts']['story_article_bullet_list_summary_prompt'] 
            self.story_user_opening_scene_summary_prompt = yaml_data['gpt_thread_prompts']['story_user_opening_scene_summary_prompt']

            # GPT Thread Prompts
            self.shorten_response_length_prompt = yaml_data['gpt_thread_prompts']['shorten_response_length']
            self.storyteller_storysuffix_prompt = yaml_data['gpt_thread_prompts']['story_suffix']
            self.storyteller_storystarter_prompt = yaml_data['gpt_thread_prompts']['story_starter']
            self.storyteller_storyprogressor_prompt = yaml_data['gpt_thread_prompts']['story_progressor']
            self.storyteller_storyfinisher_prompt = yaml_data['gpt_thread_prompts']['story_finisher']
            self.storyteller_storyclimax_prompt = yaml_data['gpt_thread_prompts']['story_climaxer']
            self.storyteller_storyender_prompt = yaml_data['gpt_thread_prompts']['story_ender']
            self.ouat_prompt_addtostory_prefix = yaml_data['gpt_thread_prompts']['story_addtostory_prefix']
            self.aboutme_prompt = yaml_data['gpt_thread_prompts']['aboutme_prompt']

            # OUAT Progression flow / Config
            self.ouat_message_recurrence_seconds = yaml_data['ouat_storyteller']['ouat_message_recurrence_seconds']
            self.ouat_story_max_counter_default = yaml_data['ouat_storyteller']['ouat_story_max_counter_default']
            self.ouat_story_progression_number = set_story_progression_number(self.ouat_story_max_counter_default)
            self.ouat_story_climax_number = set_story_climax_number(self.ouat_story_max_counter_default, self.ouat_story_progression_number)
            self.ouat_story_finisher_number = set_story_finisher_number(self.ouat_story_max_counter_default, self.ouat_story_climax_number)

            # GPT Writing Style/Theme/Tone Paramaters
            self.writing_tone = yaml_data.get('ouat-writing-parameters', {}).get('writing_tone', 'no specified writing tone')
            self.writing_style = yaml_data.get('ouat-writing-parameters', {}).get('writing_style', 'no specified writing tone')
            self.writing_theme = yaml_data.get('ouat-writing-parameters', {}).get('writing_theme', 'no specified writing tone')
        except Exception as e:
            self.logger.error(f"Error in yaml_ouat_config(): {e}")

    def yaml_depinjector_config(self, yaml_data):
        try:
            self.tts_data_folder = yaml_data['openai-api']['tts_data_folder']
            self.tts_file_name = yaml_data['openai-api']['tts_file_name']
            self.tts_voices = yaml_data['openai-api']['tts_voices']
            self.tts_volume = yaml_data['openai-api']['tts_volume']
        except Exception as e:
            self.logger.error(f"Error in yaml_depinjector_config(): {e}")

    def yaml_randomfact_json(self, yaml_data):
        try:
            self.randomfact_sleeptime = yaml_data['chatforme_randomfacts']['randomfact_sleeptime']
            self.randomfact_selected_game = os.getenv('CHATZILLA_SELECTED_GAME')
                            
            # Set random fact prompt and response based on selected game
            if self.randomfact_selected_game == 'no_game_selected':
                selected_type = 'standard'
            elif self.randomfact_selected_game != 'no_game_selected' and self.randomfact_selected_game is not None:
                selected_type = 'game'
            elif self.randomfact_selected_game == None:
                selected_type = 'standard'
            else:
                self.logger.error("randomfact_selected_game is None and was set to 'standard'")
                selected_type = 'standard'

            self.randomfact_prompt = yaml_data['chatforme_randomfacts']['randomfact_types'][selected_type]['randomfact_prompt']
            self.randomfact_response = yaml_data['chatforme_randomfacts']['randomfact_types'][selected_type]['randomfact_response']

            self.randomfact_topics_json_filepath = yaml_data['chatforme_randomfacts']['randomfact_types'][selected_type]['topics_injection_file_path']
            self.randomfact_topics = utils.load_json(path_or_dir=self.randomfact_topics_json_filepath)

            self.randomfact_areas_json_filepath = yaml_data['chatforme_randomfacts']['randomfact_types'][selected_type]['areas_injection_file_path']
            self.randomfact_areas = utils.load_json(path_or_dir=self.randomfact_areas_json_filepath)

        except Exception as e:
            self.logger.error(f"Error in yaml_randomfact_json(): {e}")

    def yaml_factchecker_config(self, yaml_data):
        try:
            self.factchecker_prompts = yaml_data['chatforme_factcheck']['chatforme_factcheck_prompts']
        except Exception as e:
            self.logger.error(f"Error in yaml_factchecker_config(): {e}")

    def update_spellcheck_config(self, yaml_data):
        self.command_spellcheck_terms_filepath = yaml_data['spellcheck_commands_filename']
        self.command_spellcheck_terms = utils.load_json(path_or_dir=self.command_spellcheck_terms_filepath)

    def update_config_from_yaml(self, yaml_data):
        try:
            
            self.twitch_bot_redirect_path = yaml_data['twitch-app']['twitch_bot_redirect_path']
            self.twitch_bot_scope = yaml_data['twitch-app']['twitch_bot_scope']

            self.gpt_model = yaml_data.get('openai-api',{}).get('assistant_model', 'gpt-3.5-turbo') 
            self.gpt_model_davinci = yaml_data.get('openai-api',{}).get('assistant_model_davinci', 'gpt-3.05-turbo') 

            self.tts_model = yaml_data.get('openai-api', {}).get('tts_model','tts-1')

        except Exception as e:
            self.logger.error(f"Error in update_config_from_yaml(): {e}")

    def _log_config(self):
        """
        Reorganized logging of ALL known config variables into distinct sections,
        based on their usage throughout the ConfigManager code.
        """

        # 1) STARTUP / EARLY CONFIG
        self.logger.info("")
        self.logger.info("==================================================")
        self.logger.info("=             1) STARTUP / EARLY CONFIG          =")
        self.logger.info("==================================================")
        self.logger.info(f"chatzilla_port_number: {self.chatzilla_port_number}")
        self.logger.info(f"abs_yaml_filepath: {self.abs_yaml_filepath}")
        self.logger.info(f"env_path: {self.env_path}")
        self.logger.info(f"keys_env_path: {self.keys_env_path}")

        # 2) KEYS & CREDENTIALS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=           2) KEYS & CREDENTIALS                =")
        self.logger.debug("==================================================")
        self.logger.debug(f"google_service_account_credentials_file: {self.google_service_account_credentials_file}")
        self.logger.debug(f"talkzillaai_userdata_table_id: {self.talkzillaai_userdata_table_id}")
        self.logger.debug(f"talkzillaai_usertransactions_table_id: {self.talkzillaai_usertransactions_table_id}")

        # 3) TWITCH CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=               3) TWITCH CONFIG                 =")
        self.logger.debug("==================================================")
        self.logger.debug(f"twitch_bot_username: {self.twitch_bot_username}")
        self.logger.debug(f"twitch_bot_channel_name: {self.twitch_bot_channel_name}")
        self.logger.debug(f"twitch_bot_display_name: {self.twitch_bot_display_name}")
        self.logger.debug(f"twitch_bot_operatorname: {self.twitch_bot_operatorname}")
        self.logger.debug(f"twitch_bot_moderators: {self.twitch_bot_moderators}")
        self.logger.debug(f"twitch_bot_redirect_path: {self.twitch_bot_redirect_path}")
        self.logger.debug(f"twitch_bot_scope: {self.twitch_bot_scope}")

        # 4) GPT MODEL & WORDCOUNTS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=            4) GPT MODEL & WORDCOUNTS           =")
        self.logger.debug("==================================================")
        self.logger.debug(f"gpt_model: {self.gpt_model}")
        self.logger.debug(f"gpt_model_davinci: {self.gpt_model_davinci}")
        self.logger.debug(f"tts_model: {self.tts_model}")  
        self.logger.debug(f"wordcount_short: {self.wordcount_short}")
        self.logger.debug(f"wordcount_medium: {self.wordcount_medium}")
        self.logger.debug(f"wordcount_long: {self.wordcount_long}")
        self.logger.debug(f"assistant_response_max_length: {self.assistant_response_max_length}")
        self.logger.debug(f"magic_max_waittime_for_gpt_response: {self.magic_max_waittime_for_gpt_response}")

        # 5) TTS VOICES / AUDIO CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=             5) TTS VOICES / AUDIO              =")
        self.logger.debug("==================================================")
        self.logger.debug(f"tts_include_voice: {self.tts_include_voice}")
        self.logger.debug(f"tts_data_folder: {self.tts_data_folder}")
        self.logger.debug(f"tts_file_name: {self.tts_file_name}")
        self.logger.debug(f"tts_voice_randomfact: {self.tts_voice_randomfact}")
        self.logger.debug(f"tts_voice_chatforme: {self.tts_voice_chatforme}")
        self.logger.debug(f"tts_voice_story: {self.tts_voice_story}")
        self.logger.debug(f"tts_voice_factcheck: {self.factcheck_voice}")
        self.logger.debug(f"tts_voice_newuser: {self.tts_voice_newuser}")
        self.logger.debug(f"tts_voice_default: {self.tts_voice_default}")
        self.logger.debug(f"tts_voice_vibecheck: {self.tts_voice_vibecheck}")
        self.logger.debug(f"chatzilla_mic_device_name: {self.chatzilla_mic_device_name}")
        # From yaml_depinjector_config
        self.logger.debug(f"tts_voices: {self.tts_voices}")
        self.logger.debug(f"tts_volume: {self.tts_volume}")

        # 6) BOTEARS CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=                 6) BOTEARS CONFIG              =")
        self.logger.debug("==================================================")
        self.logger.debug(f"botears_prompt: {self.botears_prompt}")
        self.logger.debug(f"botears_audio_path: {self.botears_audio_path}")
        self.logger.debug(f"botears_audio_filename: {self.botears_audio_filename}")
        self.logger.debug(f"botears_save_length_seconds: {self.botears_save_length_seconds}")
        self.logger.debug(f"botears_buffer_length_seconds: {self.botears_buffer_length_seconds}")

        # 7) FACTCHECK CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=              7) FACTCHECK CONFIG               =")
        self.logger.debug("==================================================")
        self.logger.debug(f"factchecker_prompts: {self.factchecker_prompts}")

        # 8) RANDOM FACT CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=             8) RANDOM FACT CONFIG              =")
        self.logger.debug("==================================================")
        self.logger.debug(f"randomfact_sleeptime: {self.randomfact_sleeptime}")
        self.logger.debug(f"randomfact_selected_game: {self.randomfact_selected_game}")
        self.logger.debug(f"randomfact_prompt: {self.randomfact_prompt}")
        self.logger.debug(f"randomfact_response: {self.randomfact_response}")
        self.logger.debug(f"randomfact_topics_json_filepath: {self.randomfact_topics_json_filepath}")
        self.logger.debug(f"randomfact_areas_json_filepath: {self.randomfact_areas_json_filepath}")

        # 9) VIBE CHECK & NEW USERS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=           9) VIBE CHECK & NEW USERS            =")
        self.logger.debug("==================================================")
        self.logger.debug(f"vibechecker_max_interaction_count: {self.vibechecker_max_interaction_count}")
        self.logger.debug(f"formatted_gpt_vibecheck_prompt: {self.formatted_gpt_vibecheck_prompt}")
        self.logger.debug(f"formatted_gpt_viberesult_prompt: {self.formatted_gpt_viberesult_prompt}")
        self.logger.debug(f"newusers_sleep_time: {self.newusers_sleep_time}")
        self.logger.debug(f"newusers_msg_prompt: {self.newusers_msg_prompt}")
        self.logger.debug(f"newusers_faiss_default_query: {self.newusers_faiss_default_query}")
        self.logger.debug(f"returningusers_msg_prompt: {self.returningusers_msg_prompt}")
        self.logger.debug(f"vibechecker_message_wordcount: {self.vibechecker_message_wordcount}")
        self.logger.debug(f"vibechecker_question_session_sleep_time: {self.vibechecker_question_session_sleep_time}")
        self.logger.debug(f"vibechecker_listener_sleep_time: {self.vibechecker_listener_sleep_time}")
        self.logger.debug(f"formatted_gpt_vibecheck_alert: {self.formatted_gpt_vibecheck_alert}")
        self.logger.debug(f"flag_returning_users_service: {self.flag_returning_users_service}")

        # 10) CHATFORME
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=                  10) CHATFORME                 =")
        self.logger.debug("==================================================")
        self.logger.debug(f"chatforme_prompt: {self.chatforme_prompt}")

        # 11) GPT HELLO WORLD
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=            11) GPT HELLO WORLD                 =")
        self.logger.debug("==================================================")
        self.logger.debug(f"twitch_bot_gpt_hello_world: {self.twitch_bot_gpt_hello_world}")
        self.logger.debug(f"gpt_hello_world: {self.gpt_hello_world}")
        self.logger.debug(f"hello_assistant_prompt: {self.hello_assistant_prompt}")

        # 12) GPT EXPLAIN
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=              12) GPT EXPLAIN CONFIG            =")
        self.logger.debug("==================================================")
        self.logger.debug(f"gpt_explain_prompts: {self.gpt_explain_prompts}")
        self.logger.debug(f"explanation_suffix: {self.explanation_suffix}")
        self.logger.debug(f"explanation_starter: {self.explanation_starter}")
        self.logger.debug(f"explanation_progressor: {self.explanation_progressor}")
        self.logger.debug(f"explanation_additional_detail_addition: {self.explanation_additional_detail_addition}")
        self.logger.debug(f"explanation_user_opening_summary_prompt: {self.explanation_user_opening_summary_prompt}")
        self.logger.debug(f"explanation_ender: {self.explanation_ender}")
        self.logger.debug(f"explanation_progression_number: {self.explanation_progression_number}")
        self.logger.debug(f"explanation_max_counter_default: {self.explanation_max_counter_default}")
        self.logger.debug(f"explanation_message_recurrence_seconds: {self.explanation_message_recurrence_seconds}")

        # 13) GPT THREADS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=               13) GPT THREADS                  =")
        self.logger.debug("==================================================")
        self.logger.debug(f"gpt_thread_names: {self.gpt_thread_names}")

        # 14) GPT ASSISTANTS & FUNCTION SCHEMAS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=      14) GPT ASSISTANTS & FUNCTION SCHEMAS     =")
        self.logger.debug("==================================================")
        self.logger.debug(f"gpt_assistants_config: {self.gpt_assistants_config}")
        self.logger.debug(f"gpt_assistants_suffix: {self.gpt_assistants_suffix}")
        self.logger.debug(f"function_schemas_path: {self.function_schemas_path}")
        self.logger.debug(f"function_schemas: {self.function_schemas}")
        self.logger.debug(f"gpt_assistants_with_functions_config: {self.gpt_assistants_with_functions_config}")

        # 15) OUAT (ONCE UPON A TIME) CONFIG
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=             15) OUAT (STORY) CONFIG            =")
        self.logger.debug("==================================================")
        self.logger.debug(f"ouat_message_recurrence_seconds: {self.ouat_message_recurrence_seconds}")
        self.logger.debug(f"ouat_story_max_counter_default: {self.ouat_story_max_counter_default}")
        self.logger.debug(f"ouat_story_progression_number: {self.ouat_story_progression_number}")
        self.logger.debug(f"ouat_story_climax_number: {self.ouat_story_climax_number}")
        self.logger.debug(f"ouat_story_finisher_number: {self.ouat_story_finisher_number}")
        self.logger.debug(f"writing_tone: {self.writing_tone}")
        self.logger.debug(f"writing_style: {self.writing_style}")
        self.logger.debug(f"writing_theme: {self.writing_theme}")
        self.logger.debug(f"newsarticle_rss_feed: {self.newsarticle_rss_feed}")
        self.logger.debug(f"story_article_bullet_list_summary_prompt: {self.story_article_bullet_list_summary_prompt}")
        self.logger.debug(f"story_user_opening_scene_summary_prompt: {self.story_user_opening_scene_summary_prompt}")
        self.logger.debug(f"shorten_response_length_prompt: {self.shorten_response_length_prompt}")
        self.logger.debug(f"storyteller_storysuffix_prompt: {self.storyteller_storysuffix_prompt}")
        self.logger.debug(f"storyteller_storystarter_prompt: {self.storyteller_storystarter_prompt}")
        self.logger.debug(f"storyteller_storyprogressor_prompt: {self.storyteller_storyprogressor_prompt}")
        self.logger.debug(f"storyteller_storyfinisher_prompt: {self.storyteller_storyfinisher_prompt}")
        self.logger.debug(f"storyteller_storyclimax_prompt: {self.storyteller_storyclimax_prompt}")
        self.logger.debug(f"storyteller_storyender_prompt: {self.storyteller_storyender_prompt}")
        self.logger.debug(f"ouat_prompt_addtostory_prefix: {self.ouat_prompt_addtostory_prefix}")
        self.logger.debug(f"aboutme_prompt: {self.aboutme_prompt}")

        # 16) SPELLCHECK
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=              16) SPELLCHECK CONFIG             =")
        self.logger.debug("==================================================")
        self.logger.debug(f"command_spellcheck_terms_filepath: {self.command_spellcheck_terms_filepath}")
        self.logger.debug(f"command_spellcheck_terms: {self.command_spellcheck_terms}")

        # 17) MISC APP SETTINGS
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=            17) MISC APP SETTINGS               =")
        self.logger.debug("==================================================")
        self.logger.debug(f"num_bot_responses: {self.num_bot_responses}")
        self.logger.debug(f"msg_history_limit: {self.msg_history_limit}")

        # 18) LOG COMPLETE
        self.logger.debug("")
        self.logger.debug("==================================================")
        self.logger.debug("=                LOG COMPLETE                    =")
        self.logger.debug("==================================================")

    def create_logger(self):
        self.logger = my_logging.create_logger(
            logger_name='logger_ConfigManagerClass', 
            debug_level=runtime_logger_level,
            stream_logs=True,
            encoding='UTF-8'
            )

if __name__ == "__main__":
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