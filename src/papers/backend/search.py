import logging
from typing import List
from fastembed import TextEmbedding

from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta

logger = logging.getLogger(__name__)

class SemanticEngine:
    """
    Singleton semantic engine.
    Ensures the FastEmbed model is loaded into memory only once and reused 
    for all vectorizations and searches to optimize resource consumption.
    """
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SemanticEngine, cls).__new__(cls)
            cls._instance._initialize_model()
        return cls._instance

    def _initialize_model(self) -> None:
        """
        Loads the embedding model into memory upon first instantiation.
        """
        settings = Settings.load_from_yaml()
        model_name = settings.search.model_name
        
        logger.info(f"Loading semantic model: {model_name}...")
        self._model = TextEmbedding(model_name=model_name)
        logger.info("Semantic model successfully loaded into memory.")

    def build_semantic_text(self, meta: GlobalDocumentMeta) -> str:
        """
        Constructs a dense, context-rich text block by joining all available 
        metadata from the document to maximize contextual understanding.
        """
        parts = [f"Title: {meta.title}"]
        
        if meta.abstract:
            parts.append(f"Abstract: {meta.abstract}")
            
        if meta.keywords:
            parts.append(f"Keywords: {', '.join(meta.keywords)}")
            
        if meta.authors:
            parts.append(f"Authors: {', '.join(meta.authors)}")
            
        if meta.institutions:
            parts.append(f"Institutions: {', '.join(meta.institutions)}")
            
        return " | ".join(parts)

    def generate_embedding(self, text: str) -> List[float]:
        """
        Converts a string of text into a mathematical vector representation.
        """
        embeddings_generator = self._model.embed([text])
        embeddings_list = list(embeddings_generator)
        
        return embeddings_list[0].tolist()