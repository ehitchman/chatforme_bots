import asyncio

from my_modules.my_logging import create_logger
from my_modules import utils
runtime_logger_level = 'WARNING'

class NewUsersService:
    def __init__(self):
        self.logger = create_logger(
            dirname='log', 
            logger_name='logger_NewUsersService', 
            debug_level=runtime_logger_level,
            mode='w',
            stream_logs=True,
            encoding='UTF-8'
            )

        #create newusers event
        self.newusers_ready_event = asyncio.Event()
        self.users_sent_messages_list = []
        
        # grab the known bots from the json file
        self.known_bots = utils.load_json(path_or_dir=r'.\data\rules\known_bots.json')
        self.known_bots_list = self.known_bots['known_bots']

    async def get_users_not_yet_sent_message(
            self,
            historic_users_list: list,
            current_users_list: list,
            users_sent_messages_list: list = None
        ) -> list:

        # Construct list of dictionaries with user details
        users_not_yet_sent_message_info_list = []

        # Use class variable if users_sent_messages_list is None
        if users_sent_messages_list is None:
            users_sent_messages_list = self.users_sent_messages_list

        # Normalize to lowercase
        historic_users_list = [user.lower() for user in historic_users_list]
        current_users_list = [user.lower() for user in current_users_list]
        users_sent_messages_list = [user.lower() for user in users_sent_messages_list]
        
        self.logger.debug("inputs:")
        self.logger.debug(f"historic_users_list: {historic_users_list}")
        self.logger.debug(f"current_users_list: {current_users_list}")
        self.logger.debug(f"users_sent_messages_list: {users_sent_messages_list}")

        # Exclude known bots
        current_users_list_excluding_bots = [user for user in current_users_list if user not in self.known_bots_list]
        self.logger.debug(f"current_users_list_excluding_bots: {current_users_list_excluding_bots}")

        # Find users not yet sent a message
        users_not_yet_sent_message = set(current_users_list_excluding_bots) - set(users_sent_messages_list)
        self.logger.info(f"users_not_yet_sent_message: {users_not_yet_sent_message}")

        for user in users_not_yet_sent_message:
            if user not in historic_users_list:
                user_type = "new"
            elif user in historic_users_list:
                user_type = "returning"
            else:
                user_type = "unknown"

            users_not_yet_sent_message_info_list.append({"username": user, "usertype": user_type})

        self.logger.debug(f"user_info_list: {users_not_yet_sent_message_info_list}")

        return users_not_yet_sent_message_info_list
    
if __name__ == "__main__":

    # Test the get_users_not_yet_sent_message() fucntion
    historic_users_list = ['user1', 'user2', 'user3']
    current_users_list = ['user1', 'user2', 'user3', 'user4', 'user5', 'streamlabs']
    users_sent_messages_list=['user1', 'user2', 'user3', 'user4']
    new_users_service = NewUsersService()
    
    print(f"known_bots_list: {new_users_service.known_bots_list}")

    result = asyncio.run(new_users_service.get_users_not_yet_sent_message(
        historic_users_list, 
        current_users_list,
        users_sent_messages_list=users_sent_messages_list
        ))
    
    print("result (result should be user5 bc streamlabs is a bot and u1-u4 has been sent a message already):")
    print(result)