"""Camada de renderização — utilitários de FFmpeg e filtros de vídeo.

Extraído de core/montage.py, que tinha 1.268 linhas misturando seleção,
construção de filtros, corte, concatenação e orquestração.

IMPORTANTE: nada de LÓGICA mudou nesta separação. As strings de filtro
são idênticas — cada uma custou depuração real (escape de vírgula,
escape de dois-pontos no Windows, pix_fmt, timestamps).
"""
