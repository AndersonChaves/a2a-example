from collections.abc import AsyncIterable
from typing import Any, Literal, Dict

import httpx
import requests

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent


memory = MemorySaver()


@tool
def get_rain_15min_from_location(
    location: str = '',
):
    """ "Use esta ferramenta para consultar a quantidade de chuva (em mm) "
        "nos últimos 15 minutos em um bairro do Rio de Janeiro. "        

    Args:
        location: O bairro do Rio de Janeiro. Pode ser [Urca, Flamengo ou Botafogo].

    Returns:
        Uma mensagem contendo o nível de chuva nos últimos 15 minutos.
    """
    url = 'https://api.dados.rio/v2/clima_pluviometro/precipitacao_15min/'

    response = requests.get(url)
    data = response.json()
    for estacao in data:
        if estacao.get("bairro", "").lower() == location.lower():
            precipitacao = estacao.get("chuva_15min", None)
            if precipitacao is not None:
                return f"A precipitação nos últimos 15 minutos em {location} foi de {precipitacao} mm."
            else:
                return f"Não há dados de precipitação disponíveis para {location}."
    return f"Bairro '{location}' não encontrado na base de dados da API."


class ResponseFormat(BaseModel):
    """Respond to the user in this format."""

    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str


class CurrencyAgent:
    SYSTEM_INSTRUCTION = (
        "Você é um agente especializado em meteorologia. "
        "Sua única função é usar a ferramenta 'get_rain_15min_from_location' "
        "para responder perguntas sobre a quantidade de chuva em bairros do Rio de Janeiro. "
        "Você não deve responder a perguntas sobre outros tópicos ou usar ferramentas para outros fins. "
        "Se o usuário perguntar sobre outro assunto, "
        "responda educadamente que você não pode ajudar com esse tópico e só pode ajudar com consultas relacionadas à chuva. "
        "Não tente responder a perguntas não relacionadas ou usar ferramentas para outros propósitos. "
        "Atribua o status de resposta como 'input_required' se o usuário precisar fornecer mais informações. "
        "Atribua o status de resposta como 'error' se houver um erro ao processar a solicitação. "
        "Atribua o status de resposta como 'completed' se a solicitação estiver completa. "        
    )

    def __init__(self):
        #self.model = ChatGoogleGenerativeAI(model='gemini-2.0-flash')
        #self.model = ChatGoogleGenerativeAI(model='gemini-1.5-pro')
        self.model = ChatGoogleGenerativeAI(model='gemini-1.5-flash')
        self.tools = [get_rain_15min_from_location]

        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=ResponseFormat,
        )

    def invoke(self, query, sessionId) -> str:
        config = {'configurable': {'thread_id': sessionId}}
        self.graph.invoke({'messages': [('user', query)]}, config)
        return self.get_agent_response(config)

    async def stream(self, query, sessionId) -> AsyncIterable[Dict[str, Any]]:
        inputs = {'messages': [('user', query)]}
        config = {'configurable': {'thread_id': sessionId}}

        for item in self.graph.stream(inputs, config, stream_mode='values'):
            message = item['messages'][-1]
            if (
                isinstance(message, AIMessage)
                and message.tool_calls
                and len(message.tool_calls) > 0
            ):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Looking up the exchange rates...',
                }
            elif isinstance(message, ToolMessage):
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Processing the exchange rates..',
                }

        yield self.get_agent_response(config)

    def get_agent_response(self, config):
        current_state = self.graph.get_state(config)
        structured_response = current_state.values.get('structured_response')
        if structured_response and isinstance(
            structured_response, ResponseFormat
        ):
            if structured_response.status == 'input_required':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            elif structured_response.status == 'error':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            elif structured_response.status == 'completed':
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': structured_response.message,
                }

        return {
            'is_task_complete': False,
            'require_user_input': True,
            'content': 'We are unable to process your request at the moment. Please try again.',
        }

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']
