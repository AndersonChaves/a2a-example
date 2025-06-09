from uuid import uuid4
import asyncclick as click

from a2a.client import A2AClient, A2ACardResolver
from a2a.types import (
    TextPart,
    Task,
    TaskState,
    Message,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    MessageSendConfiguration,
    SendMessageRequest,
    SendStreamingMessageRequest,
    MessageSendParams,
    GetTaskRequest,
    TaskQueryParams,
    JSONRPCErrorResponse,
)
from push_notification_auth import PushNotificationReceiverAuth

class TaskExecutor():
    def __init__(self, client, streaming, use_push_notifications, 
                 notification_receiver_host, notification_receiver_port):
        self.client = client
        self.streaming = streaming
        self.use_push_notifications = use_push_notifications
        self.notification_receiver_host = notification_receiver_host
        self.notification_receiver_port = notification_receiver_port

    async def completeTask(self, card, taskId, contextId):
        self.taskId = taskId
        self.contextId = contextId
        payload = self.build_payload(self.taskId, self.contextId)

        taskResult = None
        message = None
        streaming = True #aqui
        if streaming:
            answer = await self.answer_streaming(self.client, payload)
            status_sucess, taskId, event = answer
            if not status_sucess:
                print("Não foi possível concluir a task.")
                return False, contextId, taskId
            # Upon completion of the stream. Retrieve the full task if one was made.
            if taskId:
                taskResult = await self.client.get_task(
                    GetTaskRequest(
                        id=str(uuid4()),
                        params=TaskQueryParams(id=taskId),
                    )
                )
            taskResult = taskResult.root.result
        else:
            self.answer_non_streaming(self.client, payload)
            try:
                # For non-streaming, assume the response is a task or message.
                event = await self.client.send_message(
                    SendMessageRequest(
                        id=str(uuid4()),
                        params=payload,
                    )
                )
                event = event.root.result
            except Exception as e:
                print("Failed to complete the call", e)
            if not contextId:
                contextId = event.contextId
            if isinstance(event, Task):
                if not taskId:
                    taskId = event.id
                taskResult = event
            elif isinstance(event, Message):
                message = event

        if message:
            try:
                print(event.status.message.parts[0].root.text) # Aqui
            except:
                print(f'stream event => {message.model_dump_json(exclude_none=True)}')           
            return True, contextId, taskId
        state = TaskState(taskResult.status.state)
        if state.name == TaskState.completed.name:
            print(f"Resultado da task: {taskResult.artifacts[0].parts[0].root.text}")  # Access and print the desired field
        elif state.name == TaskState.input_required.name:
            
            print("A tarefa precisa de entradas adicionais:")
            print(f"O agente \"{card.name}\" informou: {taskResult.status.message.parts[0].root.text}") 
            return (
                await self.completeTask(
                    card,  # Should create a new task manager? Aproveitando
                    taskId,    # Parâmetros do anterior
                    contextId,
                ),
                contextId,
                taskId,
            )
        else:
            print("A tarefa não foi concluída com sucesso.")
            print("Status final da tarefa é:", state.name)
            ## task is complete
            return True, contextId, taskId
        ## Failure case, shouldn't reach
        return True, contextId, taskId

    def build_payload(self, taskId, contextId):
        prompt = click.prompt(
            '\nEscreva uma mensagem para o agente: (:q ou quit para sair)'
        )
        if prompt == ':q' or prompt == 'quit':
            return False, None, None

        message = Message(
            role='user',
            parts=[TextPart(text=prompt)],
            messageId=str(uuid4()),
            taskId=taskId,
            contextId=contextId,
        )

        file_path = ''
        # file_path = click.prompt(
        #     'Select a file path to attach? (press enter to skip)',
        #     default='',
        #     show_default=False,
        # )
        # if file_path and file_path.strip() != '':
        #     with open(file_path, 'rb') as f:
        #         file_content = base64.b64encode(f.read()).decode('utf-8')
        #         file_name = os.path.basename(file_path)

        #     message.parts.append(
        #         Part(
        #             root=FilePart(
        #                 file=FileWithBytes(
        #                     name=file_name, bytes=file_content
        #                 )
        #             )
        #         )
        #     )

        payload = MessageSendParams(
            id=str(uuid4()),
            message=message,
            configuration=MessageSendConfiguration(
                acceptedOutputModes=['text'],
            ),
        )
        # if use_push_notifications:
        #     payload['pushNotification'] = {
        #         'url': f'http://{notification_receiver_host}:{notification_receiver_port}/notify',
        #         'authentication': {
        #             'schemes': ['bearer'],
        #         },
        #     }
        return payload

    async def answer_streaming(self, client: A2AClient, payload):
        response_stream = await self.send_a2a_message(client, payload)
        
        async for result in response_stream:
            if isinstance(result.root, JSONRPCErrorResponse):
                print("Error: ", result.root.error)
                return False, taskId, None
            event = result.root.result
            contextId = event.contextId
            import time
            #time.sleep(2)
            if ( isinstance(event, Task) ):
                print("- Got a task event")
                taskId = event.id
                print(event.history[-1].parts[0].root.text)            
            elif (isinstance(event, TaskStatusUpdateEvent)):
                print("- Got a task status update event")
                taskId = event.taskId
                if event.final:
                    print("Task is complete.")
                else:
                    print(f"Atualizando status do agente: {event.status.message.parts[0].root.text}")
            elif (isinstance(event, TaskArtifactUpdateEvent)):
                print("- Got a task Artifact status update event")        
                taskId = event.taskId
                print(f"Resposta final: {event.artifact.parts[0].root.text}")
            elif isinstance(event, Message):
                print("- Got a message event")
                message = event
                print(f'stream Message event => {event.model_dump_json(exclude_none=True)}')
            
        return True, taskId, event
                
    async def send_a2a_message(self, client: A2AClient, payload): 
        response_stream = client.send_message_streaming(
            SendStreamingMessageRequest(
                id=str(uuid4()),
                params=payload,
            )
        )
        return response_stream