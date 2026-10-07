"""Fonti dati intercambiabili. Per passare a API-Football o Sportmonks basta
scrivere una nuova classe con gli stessi metodi e selezionarla in run.py."""
from abc import ABC, abstractmethod

import pandas as pd

import calendario
import config
import data


class FootballDataProvider(ABC):
    name: str

    @abstractmethod
    def sync(self, force: bool = False) -> None: ...

    @abstractmethod
    def matches(self) -> pd.DataFrame:
        """Partite giocate con colonne standard (h_goals, a_corners, odds_h, ...)."""

    @abstractmethod
    def fixtures(self) -> pd.DataFrame:
        """Prossime partite con le stesse colonne (statistiche vuote)."""


class FootballDataCoUkProvider(FootballDataProvider):
    name = "football-data.co.uk"

    def sync(self, force=False):
        data.download(force)

    def matches(self):
        return data.build_database()

    def fixtures(self, matches=None):
        fx = data.load_fixtures()
        if matches is not None:
            fx = calendario.merge(fx, calendario.fetch(matches, config.LEAGUES))
        return fx
