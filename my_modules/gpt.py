from classes.ArticleGeneratorClass import ArticleGenerator
from classes.ConsoleColoursClass import bcolors, printc
from my_modules.my_logging import my_logger

import os
from modules import load_env, load_yaml
import random
import requests
import openai
import re
import json


# call to chat gpt for completion TODO: Could add  limits here?
def openai_gpt_chatcompletion(messages_dict_gpt=None,
                              OPENAI_API_KEY=None, 
                              max_characters=500,
                              max_attempts=5): 
    """
    Send a message to OpenAI GPT-3.5-turbo for completion and get the response.

    Parameters:
    - messages_dict_gpt (dict): Dictionary containing the message structure for the GPT prompt.
    - OPENAI_API_KEY (str): API key to authenticate with OpenAI.

    Returns:
    str: The content of the message generated by GPT.
    """     
    openai.api_key = OPENAI_API_KEY

    #setup logger
    logger_gptchatcompletion = my_logger(dirname='log', logger_name='logger_openai_gpt_chatcompletion')
    logger_gptchatcompletion.debug(messages_dict_gpt)

    for _ in range(max_attempts):
        generated_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            #model="gpt-4-turbo",
            messages=messages_dict_gpt)
        gpt_response_text = generated_response.choices[0].message['content']
        logger_gptchatcompletion.debug(f'The --{_}--call to gpt_chat_completion had a response of {len(gpt_response_text)} characters')

        if len(gpt_response_text) < max_characters:
            logger_gptchatcompletion.info(f'The generated message was <{max_characters} characters')
            break  # Successfully got a short enough message; exit the loop
        else:
            logger_gptchatcompletion.warning(f'The generated message was >{max_characters} characters, retrying call to openai_gpt_chatcompletion')
            logger_gptchatcompletion.warning(gpt_response_text)
    else:
        message = "Maxium GPT call retries exceeded"
        logger_gptchatcompletion.error(message)        
        raise Exception(message)

    logger_gptchatcompletion.info(f'call to gpt_chat_completion ended with gpt_response_text of {len(gpt_response_text)} characters')

    return gpt_response_text


def get_random_rss_article_summary_prompt(newsarticle_rss_feed = 'http://rss.cnn.com/rss/cnn_showbiz.rss',
                                          summary_prompt = 'none',
                                          OPENAI_API_KEY = None):
    
    #Grab a random article                
    article_generator = ArticleGenerator(rss_link=newsarticle_rss_feed)
    random_article_dictionary = article_generator.fetch_random_article()

    #NOTE: rss_article_content is confusing here...
    #replace ouat_news_article_summary_prompt placeholder params
    rss_article_content = random_article_dictionary['content']
    params = {"rss_article_content":rss_article_content}
    random_article_content_prompt = summary_prompt.format(**params)

    #Final prompt dict submitted to GPT
    gpt_prompt_dict = [{'role': 'system', 'content': random_article_content_prompt}]

    random_article_content_prompt_summary = openai_gpt_chatcompletion(gpt_prompt_dict, 
                                                                      OPENAI_API_KEY=OPENAI_API_KEY, 
                                                                      max_characters=2000)
    
    return random_article_content_prompt_summary


#Generates a random prompt based on the list of standardized prompts
def rand_prompt(prompts_list=None):
    automsg_percent_chance_list = []
    automsg_prompt_topics = []
    automsg_prompts = []
    
    for key, value in prompts_list.items():
        automsg_prompt_topics.append(key)
        automsg_prompts.append(value[0])
        automsg_percent_chance_list.append(value[1])

    selected_prompt = random.choices(automsg_prompts, weights=automsg_percent_chance_list, k=1)[0]
    return selected_prompt


def format_prompt(text, replacements_dict):
    text_formatted = text.format(**replacements_dict)  
    print(f"\ntext_formatted:{text_formatted}\n")
    return text_formatted


def generate_automsg_prompt(automsg_prompts_list,
                            automsg_prompt_prefix,
                            replacements_dict):
    #setup logger
    logger_generateautomsgprompt = my_logger(dirname='log', logger_name='logger_generate_automsg_prompt')

    automsg_prompt = rand_prompt(automsg_prompts_list)   
    logger_generateautomsgprompt.debug(f"\nreplacements_dict:")
    logger_generateautomsgprompt.debug(replacements_dict)    
    logger_generateautomsgprompt.debug(f"\nautomsg_prompt:")
    logger_generateautomsgprompt.debug(automsg_prompt)    

    gpt_automsg_prompt =  automsg_prompt_prefix + automsg_prompt
    
    gpt_prompt_final = format_prompt(text=gpt_automsg_prompt,
                                     replacements_dict=replacements_dict)
    
    printc(f"\nAUTMSG: These are the variables for AUTOMSG prompt", bcolors.WARNING)
    printc(f"AUTOMSG gpt_prompt_final:{gpt_prompt_final}", bcolors.OKBLUE)  
    return gpt_prompt_final


def generate_ouat_prompt(gpt_ouat_prompt,
                         replacements_dict):
    ouat_prompt_formatted = format_prompt(gpt_ouat_prompt,
                                          replacements_dict=replacements_dict)
    return ouat_prompt_formatted

def combine_msghistory_and_prompt(prompt_text,
                                  msg_history_dict):
    #Final prompt dict submitted to GPT
    gpt_prompt_dict = [{'role': 'system', 'content': prompt_text}]

    #Final combined prompt dictionary (historic + prompt)
    messages_dict_gpt = msg_history_dict + gpt_prompt_dict
    
    return messages_dict_gpt


def get_models(api_key=None):
    """
    Function to fetch the available models from the OpenAI API.

    Args:
        api_key (str): The API key for the OpenAI API.

    Returns:
        dict: The JSON response from the API containing the available models.
    """
    url = 'https://api.openai.com/v1/models'

    headers = {
        'Authorization': f'Bearer {api_key}'
    }

    response = requests.get(url, headers=headers)

    return response.json()


if __name__ == '__main__':
    yaml_data = load_yaml(yaml_dirname='config')
    load_env(env_dirname='config')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    gpt_models = get_models(OPENAI_API_KEY)
    json.dumps(gpt_models, indent=4)
    # #test1 -- get_random_rss_article_summary_prompt
    # summary_prompt = yaml_data['ouat_news_article_summary_prompt']
    # response = get_random_rss_article_summary_prompt(newsarticle_rss_feed='http://rss.cnn.com/rss/cnn_showbiz.rss',
    #                                                 summary_prompt=summary_prompt,
    #                                                 OPENAI_API_KEY=OPENAI_API_KEY)
    # print(response)




