"""Совместимость Torch на Windows: шум, который не влияет на работу Зипки."""

from __future__ import annotations

import logging

_quieted = False


def quiet_torch_noise() -> None:
    """Скрыть известный harmless warning: triton отсутствует (Windows/CUDA).

    Triton для PyTorch на Windows обычно недоступен; flop counting Зипке не нужен.
    """
    global _quieted
    if _quieted:
        return
    _quieted = True
    logging.getLogger("torch.utils.flop_counter").setLevel(logging.ERROR)
