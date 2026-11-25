"""Selection strategies behind a common Selector interface."""

from vanrain.selector.base import Selector, SelectorConfig, Strategy
from vanrain.selector.bfs import BFSSelector

__all__ = ["BFSSelector", "Selector", "SelectorConfig", "Strategy"]
