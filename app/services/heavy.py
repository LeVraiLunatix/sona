"""Un seul gros travail à la fois (téléchargement + vérification, détourage d'une cover) :
sur une petite machine (1 Go), en lancer plusieurs saturait la mémoire et figeait le serveur."""

from __future__ import annotations

import asyncio

slot = asyncio.Semaphore(1)
