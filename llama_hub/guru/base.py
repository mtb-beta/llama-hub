"""Guru cards / collections reader."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, List, Optional
import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
import warnings
import pandas as pd
import re

from llama_index import download_loader
from llama_index.readers.base import BaseReader
from llama_index.readers.schema.base import Document

logger = logging.getLogger(__name__)

class GuruReader(BaseReader):
    """Guru cards / collections reader."""

    def __init__(self, guru_username: str, api_token: str) -> None:
        """Initialize GuruReader.

        Args:
            guru_username: Guru username.
            api_token: Guru API token. This can be personal API keys or collection based API keys. Note this is not the same as your password.
        """
        self.guru_username = guru_username
        self.api_token = api_token
        self.guru_auth=HTTPBasicAuth(guru_username, api_token)


    def load_data(self, collection_ids: Optional[List[str]] = None, card_ids: Optional[List[str]] = None) -> List[Document]:
        """Load data from Guru.
        
        Args:
            collection_ids: List of collection ids to load from. Only pass in card_ids or collection_ids, not both.
            card_ids: List of card ids to load from. Only pass in card_ids or collection_ids, not both.

        Returns:
            List[Document]: List of documents.
        
        """
        assert  (collection_ids is None) or (card_ids is None), "Only pass in card_ids or collection_ids, not both."
        assert  (collection_ids is not None) or (card_ids is not None), "Pass in card_ids or collection_ids."

        if collection_ids is not None:
            card_ids = self._get_card_ids_from_collection_ids(collection_ids)

        return [self._get_card_info(card_id) for card_id in card_ids]
    
    def _get_card_ids_from_collection_ids(self, collection_ids: List[str]) -> List[str]:
        """Get card ids from collection ids."""
        all_ids = []
        for collection_id in collection_ids:
            card_ids = self._get_card_ids_from_collection_id(collection_id)
            all_ids.extend(card_ids)
        return all_ids
    
    def _get_card_ids_from_collection_id(self, collection_id: str) -> List[str]:
        records = []
        next_page = True
        initial_url = "https://api.getguru.com/api/v1/search/cardmgr?queryType=cards"
        
        response = requests.get(initial_url, auth=self.guru_auth)
        records.extend(response.json())
        
        while next_page:
            try:
                url = response.headers['Link']
                url_pattern = r'<(.*?)>'
                url_match = re.search(url_pattern, url)
                url = url_match.group(1)
            except Exception as e:
                next_page = False
                break
                
            response = requests.get(url, auth=self.guru_auth)
            records.extend(response.json())
        
        cards = pd.DataFrame.from_records(records)
        df_normalized = pd.json_normalize(cards['collection'])
        df_normalized.columns = ['collection_' + col for col in df_normalized.columns]
        df = pd.concat([cards, df_normalized], axis=1)
        df = df[df.collection_id == collection_id]
        return list(df['id'])
    
    def _get_card_info(self, card_id: str) -> Any:
        """Get card info.
        
        Args:
            card_id: Card id.

        Returns:
            Document: Document.
        """
        url = f"https://api.getguru.com/api/v1/cards/{card_id}/extended"
        headers = {"accept": "application/json"}
        response = requests.get(url, auth=self.guru_auth, headers=headers)
        
        if response.status_code == 200:
            title = response.json()['preferredPhrase']
            html = response.json()['content']   #i think this needs to be loaded
            content = self._clean_html(html)
            collection = response.json()['collection']['name']


            metadata = {
                "title": title,
                "collection": collection,
                "card_id": card_id,
                "guru_link": self._get_guru_link(card_id),
            }   

            doc = Document(text=content, extra_info=metadata)
            return doc
        else:
            logger.warning(f"Could not get card info for {card_id}.")
            return None

    @staticmethod
    def _clean_html(text: str) -> str:
        """
        Cleans HTML content by fetching its text representation using BeautifulSoup.
        """
        if text is None:
            return ""

        if isinstance(text, str):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                soup = BeautifulSoup(text, 'html.parser')
                cleaned_text = soup.get_text()
            return cleaned_text
        
        return str(text)
    
    def _get_guru_link(self, card_id) -> str:
        """
        takes a guru "ExternalId" from meta data and returns the link to the guru card
        """
        url = f"https://api.getguru.com/api/v1/cards/{card_id}/extended"
        headers = {
            "accept": "application/json",
        }
        response = requests.get(url, headers=headers, auth=self.guru_auth)
        if response.status_code == 200:
            slug =  response.json()['slug']
        else:
            raise RuntimeError(f"Guru link doesn't exist: {response.status_code}") 

        return f'https://app.getguru.com/card/{slug}'
