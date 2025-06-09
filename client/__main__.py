import asyncio
import urllib
import httpx

from task_executor import TaskExecutor
import asyncclick as click

from a2a.client import A2AClient, A2ACardResolver
from push_notification_auth import PushNotificationReceiverAuth

@click.command()
@click.option('--agent', default='http://localhost:10000')
@click.option('--session', default=0)
@click.option('--history', default=False)
@click.option('--use_push_notifications', default=False)
@click.option('--push_notification_receiver', default='http://localhost:5000')
async def cli(
    agent,
    session,
    history,
    use_push_notifications: bool,
    push_notification_receiver: str,
):
    app = App(agent, session, history, use_push_notifications, 
            push_notification_receiver)
    await app.run()    

class App():
    def __init__(self, agent, session, history, use_push_notifications, 
            push_notification_receiver):
        self.client_agent = agent
        self.session = session
        self.history = history
        self.use_push_notifications = use_push_notifications
        self.push_notification_receiver = push_notification_receiver
        self.card = None
        self.notification_receiver_host = None
        self.notification_receiver_port = None
        
    async def run(self):
        print("App is running...")
        async with httpx.AsyncClient(timeout=30) as httpx_client:        
            await self.parse_parameters(httpx_client)

            if self.use_push_notifications:
                self.enable_push_notifications(
                    self.notification_receiver_host, self.notification_receiver_port)

            client = A2AClient(httpx_client, agent_card=self.card)
            streaming = self.card.capabilities.streaming
            continue_loop = True
            while continue_loop:
                print('=========  starting a new task ======== ')
                task_executor = TaskExecutor(client, streaming, self.use_push_notifications, 
                 self.notification_receiver_host, self.notification_receiver_port)
                continue_loop, contextId, taskId = await task_executor.completeTask(
                    self.card, taskId = None, contextId = None)
                
                if self.history and continue_loop:
                    self.print_history(client, taskId)

    async def parse_parameters(self, httpx_client):
        card_resolver = A2ACardResolver(httpx_client, self.client_agent)
        self.card = await card_resolver.get_agent_card()

        print('======= Agent Card ========')
        print(self.card.model_dump_json(exclude_none=True))

        notif_receiver_parsed = urllib.parse.urlparse(
            self.push_notification_receiver)
        self.notification_receiver_host = notif_receiver_parsed.hostname
        self.notification_receiver_port = notif_receiver_parsed.port

    async def enable_push_notifications(self, notification_receiver_host, 
                                        notification_receiver_port):
        from hosts.cli.push_notification_listener import (
                    PushNotificationListener,
                )

        notification_receiver_auth = PushNotificationReceiverAuth()
        await notification_receiver_auth.load_jwks(
            f'{self.client_agent}/.well-known/jwks.json'
        )

        push_notification_listener = PushNotificationListener(
            host=notification_receiver_host,
            port=notification_receiver_port,
            notification_receiver_auth=notification_receiver_auth,
        )
        push_notification_listener.start()

    async def print_history(self, client, taskId):
        print('========= history ======== ')
        task_response = await client.get_task(
            {'id': taskId, 'historyLength': 10}
        )
        print(
            task_response.model_dump_json(
                include={'result': {'history': True}}
            )
        )                    

if __name__ == '__main__':
    asyncio.run(cli())
