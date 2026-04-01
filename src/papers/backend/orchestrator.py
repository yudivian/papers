import asyncio
from typing import List, Optional, Dict
from beaver import BeaverDB

from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta
from papers.backend.data_sources import get_data_source

class DiscoveryOrchestrator:
    """
    Manages complex document discovery workflows across multiple data providers.

    The orchestrator acts as a bridge between the high-level API routers and 
    the low-level data adapters. It implements high-level logic such as 
    cascading DOI resolution (waterfall pattern) and parallelized semantic 
    broadcasting, ensuring that system resource usage is optimized through 
    the use of asynchronous concurrency.
    """
    def __init__(self, settings: Settings, db: BeaverDB, user_id: str):
        """
        Initializes the orchestrator with the necessary execution context.

        Args:
            settings: The global application configuration.
            db: The persistent metadata and vector store.
            user_id: The identifier of the user initiating the request.
        """
        self.settings = settings
        self.db = db
        self.user_id = user_id

    async def resolve_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """
        Resolves a unique document by its DOI using a prioritized waterfall strategy.

        This method iterates through the available data sources in the order 
        defined by the configuration. It returns the first successful match 
        found, effectively treating the local cache as a primary high-speed 
        layer before falling back to external network-bound providers.

        Args:
            doi: The Digital Object Identifier to resolve.

        Returns:
            Optional[GlobalDocumentMeta]: The hydrated metadata if found; 
                                          None otherwise.
        """
        for source_name in self.settings.data_sources.priority:
            source = get_data_source(
                source_name, 
                settings=self.settings, 
                db=self.db, 
                user_id=self.user_id
            )
            meta = await source.fetch_by_doi(doi)
            if meta:
                return meta
        return None

    async def search(
        self, 
        query: str, 
        limit: int = 10, 
        target_source: Optional[str] = None
    ) -> Dict[str, List[GlobalDocumentMeta]]:
        """
        Executes a semantic search across multiple providers in parallel.

        If a target_source is specified, the search is restricted to that 
        specific adapter. Otherwise, the orchestrator broadcasts the query 
        to all providers listed in the priority configuration using 
        asyncio.gather. 

        The results are returned as a dictionary where keys represent the 
        source names and values contain the list of matching metadata objects, 
        allowing the client interface to handle presentation logic.

        Args:
            query: The natural language search string.
            limit: The maximum number of results to retrieve per source.
            target_source: An optional identifier for a single data source.

        Returns:
            Dict[str, List[GlobalDocumentMeta]]: A mapping of source names to 
                                                 their respective result lists.
        """
        if target_source:
            source = get_data_source(
                target_source, 
                settings=self.settings, 
                db=self.db, 
                user_id=self.user_id
            )
            results = await source.search_by_text(query, limit)
            return {target_source: results}

        source_names = self.settings.data_sources.priority
        tasks = []
        for name in source_names:
            source = get_data_source(
                name, 
                settings=self.settings, 
                db=self.db, 
                user_id=self.user_id
            )
            tasks.append(source.search_by_text(query, limit))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_map = {}
        for name, res in zip(source_names, results_list):
            if isinstance(res, Exception):
                final_map[name] = []
            else:
                final_map[name] = res
                    
        return final_map