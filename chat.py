import time
import uuid
from datetime import datetime
from asyncio.streams import StreamReader, StreamWriter
import sys
import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any


''' DATA CLASSES '''

@dataclass
class ChatMsg:
  user: str
  msg: bytes

  def __post_init__(self):
    self.msg = self.msg.rstrip(b'\n')
    logging.debug("New Msg Created: %s", self)

@dataclass
class Peer:
  client_id: uuid.UUID
  peername: Any
  display_name: str
  connect_time: datetime
  reader: StreamReader
  writer: StreamWriter

@dataclass
class ChatServer:
  messages: list[ChatMsg] = field(default_factory=list)
  peers: dict[str, Peer] = field(default_factory=dict)


''' SERVER '''

async def send_msg(peer: Peer, msg_bytes: bytes):
  logging.debug("Sending msg to peer %s with length %d", peer.client_id, len(msg_bytes))
  try:
    peer.writer.write(msg_bytes)
    await peer.writer.drain()
  except Exception:
    logging.info("Failed to send msg to client: %s", peer.client_id, exc_info=True)
  logging.debug("Done sending msg to peer %s with length %d", peer.client_id, len(msg_bytes))

def user_prompt(peer: Peer):
  return "[{}]> ".format(peer.display_name).encode('utf-8')

def format_msg(msg: ChatMsg):
  return "[{}]> ".format(msg.user).encode('utf-8') + msg.msg

async def publish_msg(chat_server: ChatServer, client_id: uuid.UUID, msg: ChatMsg):
  msg_bytes = b'\n' + format_msg(msg)
  tasks = set()
  for peer_id, peer in chat_server.peers.items():
    if peer_id == client_id:
      continue
    peer_msg_bytes = msg_bytes + b'\n' + user_prompt(peer)
    tasks.add(asyncio.create_task(send_msg(peer, peer_msg_bytes)))
  return tasks


async def handle_new_user(chat_server: ChatServer, client_id: uuid.UUID):
  client = chat_server.peers[client_id]
  peername = client.peername
  display_name = client.display_name
  reader = client.reader
  writer = client.writer
  logging.info("[%s] Client connected from %s (display_name: %s)", client_id, peername, display_name)

  try:
    writer.write("Welcome to the chat server {}!\n".format(display_name).encode('utf-8'))

    if chat_server.messages:
      writer.write(b"Chat history:\n")
      for msg in chat_server.messages[-10:]:
        writer.write(format_msg(msg) + b'\n')

    if len(chat_server.peers) > 1:
      writer.write(b"Online Users:\n")
      for peer_id, peer in chat_server.peers.items():
        if peer_id == client_id:
          continue
        writer.write("  {}\n".format(peer.display_name).encode('utf-8'))
    else:
      writer.write(b"No users online\n")

    publishing_msgs = set()
    while True:
      writer.write("[{}]> ".format(display_name).encode('utf-8'))
      await writer.drain()
      line = await reader.readline()
      if not line:
        logging.info("[%s] Client sent eof", client_id)
        try:
          writer.write(b'\n')
          await writer.drain()
        except Exception:
          logging.debug("[%s] Tried sending one last new line to client, but failed", client_id, exc_info=True)
        break
      msg = ChatMsg(display_name, line)
      chat_server.messages.append(msg)
      publishing_msgs.update(await publish_msg(chat_server, client_id, msg))
      if publishing_msgs:
        _, publishing_msgs = await asyncio.wait(publishing_msgs, timeout=0)
  except ConnectionResetError:
    logging.info("[%s] Client connection reset", client_id)
  if publishing_msgs:
    for publishing_msg in publishing_msgs:
      publishing_msg.cancel()
    await asyncio.wait(publishing_msgs)


async def client_connected(chat_server: ChatServer, reader: StreamReader, writer: StreamWriter):
  connect_time = datetime.now()
  client_id = uuid.uuid4()
  peername = writer.get_extra_info('peername')
  if peername is None:
    display_name = str(client_id)[:8]
  elif isinstance(peername, tuple) and len(peername) >= 2:
    display_name = f"{peername[0]}:{peername[1]}"
  else:
    display_name = str(peername)[:8]

  chat_server.peers[client_id] = Peer(client_id, peername, display_name, connect_time, reader, writer)

  try:
    await handle_new_user(chat_server, client_id)
  except Exception:
    logging.warning("[%s] An uncaught exception occurred while handling client", client_id, exc_info=True)
  finally:
    del chat_server.peers[client_id]
    writer.close()


async def start_server(port: int):
  logging.info("Starting server on port: %d", port)

  chat_server = ChatServer()

  def handle_client_connected(reader, writer):
    return client_connected(chat_server, reader, writer)

  async with await asyncio.start_server(handle_client_connected, port=port) as server:
    await server.serve_forever()


''' STARTUP '''

def run(port: int):
  port = int(port)
  try:
    asyncio.run(start_server(port))
    return 0
  except KeyboardInterrupt:
    logging.info("Server was killed by SIGINT")
  except:
    logging.warning("Server exited with an uncaught exception!", exc_info=True)
    return 1

def setup_logger(verbose: int):
  black, red, green, yellow, blue, magenta, cyan, white = range(8)
  reset_seq = "\033[0m"
  color_seq = "\033[1;{}m"

  color_section = color_seq + "{}" + reset_seq

  if verbose == 0:
    level = logging.WARNING
  elif verbose == 1:
    level = logging.INFO
  else:
    level = logging.DEBUG

  format = "[%(asctime)s %(levelname)s %(module)s:%(lineno)d] %(message)s"
  datefmt = "%Y-%m-%d %H:%M:%S"

  logging.basicConfig(level=level, format=format, datefmt=datefmt)

  logging.addLevelName(logging.INFO, color_section.format(30 + blue, logging.getLevelName(logging.INFO)))
  logging.addLevelName(logging.WARNING, color_section.format(30 + yellow, logging.getLevelName(logging.WARNING)))
  logging.addLevelName(logging.ERROR, color_section.format(30 + red, logging.getLevelName(logging.ERROR)))

def main():
  parser = argparse.ArgumentParser(description='A simple chat server')
  parser.add_argument('port', type=int, help='The port to host the server on')
  parser.add_argument('--verbose', '-v', action='count', default=0)
  args = parser.parse_args()

  setup_logger(args.verbose)
  return run(args.port)

if __name__ == '__main__':
  sys.exit(main())
