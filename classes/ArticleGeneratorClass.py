import requests
import numpy as np
from bs4 import BeautifulSoup
from my_modules import utils

# from classes.ConsoleColoursClass import bcolors, printc
from my_modules.my_logging import create_logger

class ArticleGenerator:
    def __init__(self, rss_link="http://rss.cnn.com/rss/cnn_showbiz.rss"):
        self.rss_link = rss_link
        self.articles = []
        self.article_details = []

        self.logger = create_logger(
            dirname='log', 
            logger_name='ArticleGeneratorClass',
            debug_level='INFO',
            mode='w',
            stream_logs=True
            )

    def fetch_articles(self):
        response = requests.get(self.rss_link)
        if response.status_code != 200:
            print("Failed to fetch the RSS feed.")
            return []
        
        soup = BeautifulSoup(response.content, 'xml')
        self.articles = []
        
        for item in soup.find_all('item'):
            article_dict = {
                'title': item.title.string if item.title else "N/A",
                'link': item.link.string if item.link else "N/A",
                'pub_date': item.pubDate.string if item.pubDate else "N/A",
                'description': item.description.string if item.description else "N/A"
                }
            self.articles.append(article_dict)

        self.logger.info(f"Successfully fetched --{len(self.articles)}-- article titles and links")
        return self.articles

    def fetch_random_article_content(self, article_char_trunc=1200):
        found_article = False
        disallowed_terms_filepath = r'.\data\rules\disallowed_terms.json'
        disallowed_terms = utils.load_json(path_or_dir=disallowed_terms_filepath)
        list_of_disallowed_terms = disallowed_terms['disallowed_terms']
        
        if not self.articles:
            self.logger.info("Missing URL or article data")
            self.logger.warning("Missing URL or article data.")
            return ['']
        
        while found_article == False:
            random_article_link = np.random.choice(self.articles)['link']
            
            try:
                response = requests.get(random_article_link)
                response.raise_for_status()  # This will raise if HTTP request returned an unsuccessful status code
            except requests.RequestException as e:
                self.logger.warning(f"Failed to fetch the article at {random_article_link}. Error: {e}")
                self.logger.warning(f"Failed to fetch the article at {random_article_link}. Error: {e}")
                return ['']

            try:
                soup = BeautifulSoup(response.content, 'html.parser')
                content_html_soup = soup.find('div', {'class': 'article__content'})
            except Exception as e:
                self.logger.error(f"Error during parsing the article at {random_article_link}. Error: {e}")
                self.logger.warning(f"Error during parsing the article at {random_article_link}. Error: {e}")
                return ['']

            if content_html_soup:
                content_text = content_html_soup.get_text()
                random_article_content = self.clean_html_text(content_text)
                found_article = False if self.check_for_disallowed_terms(
                    article_content=random_article_content,
                    list_of_disallowed_terms=list_of_disallowed_terms
                    ) else True
                
                if found_article:
                    self.logger.info(f"Successfully fetched article with content  (source:{random_article_link}, preview: {random_article_content[:300]}...)")
                else:
                    self.logger.debug(f"\nSuccessfully fetched article but it contained disallowed_terms (source: {random_article_link}) ")   
            else: 
                self.logger.debug(f"\nSuccessfully fetched article but it contained no content.  Trying again... \n(source: {random_article_link}")

        trimmed_article = random_article_content[:article_char_trunc]
        return trimmed_article

    def check_for_disallowed_terms(
            self,
            article_content,
            list_of_disallowed_terms
            ):
        for term in list_of_disallowed_terms:
            if term.lower() in article_content.lower():
                return True
        return False

    def clean_html_text(self, text):
        import re

        # Remove HTML tags
        text = re.sub(r'<.*?>', ' ', text)
        
        # Replace common HTML character codes
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&quot;', '"', text)
        
        # Remove or replace special characters like '\t', '\r', '\xa0', etc.
        text = re.sub(r'[\t\r\xa0]', ' ', text)

        # Remove multiple spaces with a single space
        text = re.sub(r'\s+', ' ', text).strip()

        # Remove any leading or trailing spaces
        text = text.strip()

        # Remove multiple spaces but keep single '\n'
        text = re.sub(r'(?<!\n) +', ' ', text)
        text = re.sub(r' +(?!\n)', ' ', text)
        
        # Remove any leading or trailing spaces but keep leading or trailing newlines
        text = text.strip(' ')

        # Remove multiple spaces but keep single '\n'
        text = re.sub(r'(?<!\n) +', ' ', text)
        text = re.sub(r' +(?!\n)', ' ', text)

        # Remove any leading or trailing spaces but keep leading or trailing newlines
        text = text.strip(' ')

        # Make sure it ends with the last complete sentence.
        sentence_match = re.findall(r'[^.!?]*[.!?]', text)
        if sentence_match:
            text = ''.join(sentence_match)
        elif text and text[-1] not in ".!?":
            text = text + '.'

        return text

def main(rss_link=None):
    article_generator = ArticleGenerator(rss_link=rss_link)
    random_article_dictionary = article_generator.fetch_random_article_content()
    print(random_article_dictionary['content'])

if __name__ == "__main__":
    main(rss_link="http://rss.cnn.com/rss/cnn_showbiz.rss")


