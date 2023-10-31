



import os
import requests
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError
import pandas as pd

from my_modules.utils import get_datetime_formats, format_record_timestamp, write_query_to_file
from my_modules.config import load_env, load_yaml
import json
from my_modules import my_logging
from my_modules import utils #write_json_to_file, write_query_to_file

from classes.MessageHandlerClass import MessageHandler

class TwitchChatBQUploader:
    def __init__(self):
        
        load_env()
        self.yaml_data = load_yaml()

        self.logger = my_logging.my_logger(dirname='log', 
                                           logger_name='logger_ChatUploader',
                                           debug_level='INFO',
                                           mode='w',
                                           stream_logs=True)
        self.logger.debug('TwitchChatBQUploader Logger initialized.')

        self.twitch_broadcaster_author_id = os.getenv('TWITCH_BROADCASTER_AUTHOR_ID')
        self.twitch_bot_moderator_id = os.getenv('TWITCH_BOT_MODERATOR_ID')
        self.twitch_bot_client_id = os.getenv('TWITCH_BOT_CLIENT_ID')
        self.twitch_bot_access_token = os.getenv('TWITCH_BOT_ACCESS_TOKEN')
        self.bq_client = bigquery.Client()

        #also set in twitch_bot.py
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'config/keys/eh-talkzilla-ai-1bcb1963d5b4.json'

        #BQ Table IDs
        self.userdata_table_id=self.yaml_data['twitch-ouat']['talkzillaai_userdata_table_id']
        self.usertransactions_table_id=self.yaml_data['twitch-ouat']['talkzillaai_usertransactions_table_id']

        self.channel_viewers_list_dict_temp = []
        self.channel_viewers_queue = []

    def escape_sql_string(value):
        return value.replace("'", "''").replace("\\", "\\\\")
    
    def get_channel_viewers(self,
                            bearer_token=None) -> object:
        self.logger.debug(f'Getting channel viewers with bearer_token')
        base_url='https://api.twitch.tv/helix/chat/chatters'
        params = {
            'broadcaster_id': self.twitch_broadcaster_author_id,
            'moderator_id': self.twitch_bot_moderator_id
        }
        headers = {
            'Authorization': f'Bearer {bearer_token}',
            'Client-Id': self.twitch_bot_client_id
        }
        response = requests.get(base_url, params=params, headers=headers)
        self.logger.debug(f'Received response: {response}')

        utils.write_json_to_file(
            self, response.json(), 
            variable_name_text='channel_viewers', 
            dirname='log/get_chatters_data'
            )
        self.logger.debug('Wrote response.json() to file...')
        
        return response

    def process_channel_viewers(self, response) -> list[dict]:
        self.logger.debug('Processing channel viewers response')
        timestamp = get_datetime_formats()['sql_format']
        
        if response.status_code == 200:
            self.logger.debug("Response.json(): %s", response.json())
            response_json = response.json()
            channel_viewers_list_dict = response_json['data']
            for item in channel_viewers_list_dict:
                item['timestamp'] = timestamp
            self.logger.debug(f"channel_viewers_list_dict:")
            self.logger.debug(channel_viewers_list_dict)
        else:
            self.logger.error("Failed: %s, %s", response.status_code, response.text)
            response.raise_for_status()
        
        return channel_viewers_list_dict

    def queue_channel_viewers(self, records: list[dict]) -> None:
        updated_channel_viewers_queue = self.channel_viewers_queue
        updated_channel_viewers_queue.extend(records)

        df = pd.DataFrame(updated_channel_viewers_queue)
        df = df.sort_values(['user_id', 'timestamp'])
        df = df.drop_duplicates(subset='user_id', keep='last')
        self.logger.info(f'channel_viewers_queue deduplicated has {len(df)} rows')

        self.channel_viewers_queue = df.to_dict('records')

    def generate_bq_users_query(self, records: list[dict]) -> str:

        # Build the UNION ALL part of the query
        union_all_query = " UNION ALL ".join([
            f"SELECT '{viewer['user_id']}' as user_id, '{viewer['user_login']}' as user_login, "
            f"'{viewer['user_name']}' as user_name, PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', '{viewer['timestamp']}') as last_seen"
            for viewer in records
        ])
        utils.write_query_to_file(formatted_query=union_all_query, 
                            dirname='log/queries',
                            queryname='channelviewers_query')
        
        # Add the union all query to our final query to be sent to BQ jobs
        merge_query = f"""
            MERGE {self.userdata_table_id} AS target
            USING (
                {union_all_query}
            ) AS source
            ON target.user_id = source.user_id
            WHEN MATCHED THEN
                UPDATE SET
                    target.user_login = source.user_login,
                    target.user_name = source.user_name,
                    target.last_seen = source.last_seen
            WHEN NOT MATCHED THEN
                INSERT (user_id, user_login, user_name, last_seen)
                VALUES(source.user_id, source.user_login, source.user_name, source.last_seen);
        """
        utils.write_query_to_file(formatted_query=merge_query, 
                            dirname='log/queries',
                            queryname='channelviewers_query_final')
        
        self.logger.info("The users table query was generated")
        self.logger.debug("This is the users table merge query:")
        self.logger.debug(merge_query)
        return merge_query
  
    def get_process_queue_create_channel_viewers_query(self, bearer_token) -> str:
        
        #Response from twitch API
        response = self.get_channel_viewers(bearer_token=bearer_token)

        #retrieves list of dicts
        channel_viewers_records = self.process_channel_viewers(response=response)
        
        #queues/updates the self.channel_viewers_queue
        self.queue_channel_viewers(records=channel_viewers_records)

        #generates a query based on the queued viewers
        channel_viewers_query = self.generate_bq_users_query(records=self.channel_viewers_queue)

        return channel_viewers_query
    
    def generate_bq_user_interactions_query(self, records: list[dict]) -> str:
        union_queries = []

        for record in records:
            user_id = record.get('user_id')
            channel = record.get('channel')
            content = record.get('content')
            timestamp = record.get('timestamp')
            user_badges = record.get('badges')
            color = record.get('tags').get('color', '') if record.get('tags') else ''
            
            union_query = f"""
                SELECT '{user_id}' as user_id, '{channel}' as channel, '{content}' as content, PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', '{timestamp}') as timestamp, '{user_badges}' as user_badges, '{color}' as color
            """

            union_queries.append(union_query)

        full_query = f"""
            INSERT INTO {self.usertransactions_table_id} (user_id, channel, content, timestamp, user_badges, color)
            { ' UNION ALL '.join(union_queries) }
        """

        utils.write_query_to_file(formatted_query=full_query, 
                            dirname='log/queries',
                            queryname='viewerinteractions_query_final')
        self.logger.info("The user_interactions query was generated")
        self.logger.debug("This is the user_interactions insert query:")
        self.logger.debug(full_query)
        return full_query

    def send_to_bq(self, query):
        # Initialize a BigQuery client
        client = bigquery.Client()

        try:
            # Start the query job
            self.logger.info("Starting BigQuery job...")
            query_job = client.query(query)

            # Wait for the job to complete (this will block until the job is done)
            self.logger.info(f"Executing query...")
            query_job.result()

            # Log job completion
            self.logger.info(f"Query job {query_job.job_id} completed successfully.")

        except GoogleAPIError as e:
            # Log any API errors
            self.logger.error(f"BigQuery job failed: {e}")

        except Exception as e:
            # Log any other exceptions
            self.logger.error(f"An unexpected error occurred: {e}")

        else:
            # Optionally, get and log job statistics
            job_stats = query_job.query_plan
            self.logger.info(f"Query plan: {job_stats}")

# if __name__ == '__main__':
#     chatdataclass = TwitchChatBQUploader()
#     chatdataclass.get_channel_viewers()
#     self.logger.debug('Execution completed.')