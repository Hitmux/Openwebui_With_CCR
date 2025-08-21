# author: hitmux674@gmail.com
# LICENSE: AGPLv3
# Date: 2025-8-21
# Version: 1.0
# Gtihub: https://github.com/hitmux/Openwebui_With_CCR

import asyncio
import argparse

LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 4567 # Your Claude Code Port

UPSTREAM_HOST = '127.0.0.1'
UPSTREAM_PORT = 3456 # Your Claude Code Router Port


BAD_BLOCK_SIGNATURE = b'"isNewTopic": true'
BLOCK_START_MARKER = b'event: message_start'
BLOCK_END_MARKER = b'event: message_stop\ndata: {"type":"message_stop"}\n\n'


async def forward_client_to_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):

    try:
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[C->S] Error forwarding client to server: {e}")
    finally:
        if not writer.is_closing():
            writer.close()
            await writer.wait_closed()


async def forward_server_to_client_with_fix(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):

    buffer = b''
    try:
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data:
                break
            
            buffer += data
            
            while True:
                try:
                    start_pos = buffer.find(BLOCK_START_MARKER)
                    if start_pos == -1:
                        if buffer:
                            writer.write(buffer)
                            await writer.drain()
                            buffer = b''
                        break
                    
                    end_pos = buffer.find(BLOCK_END_MARKER, start_pos)
                    if end_pos == -1:
                        break

                    block_end = end_pos + len(BLOCK_END_MARKER)
                    message_block = buffer[start_pos:block_end]
                    
                    if BAD_BLOCK_SIGNATURE in message_block:
                        print(f"--- [PROXY] Detected and dropped a metadata block! ---")
                    else:
                        writer.write(message_block)
                        await writer.drain()

                    buffer = buffer[block_end:]
                
                except Exception as e:
                    print(f"Error processing buffer: {e}")
                    buffer = b''
                    break

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[S->C] Error forwarding server to client: {e}")
    finally:
        if not writer.is_closing():
            writer.close()
            await writer.wait_closed()


async def handle_client_connection(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):

    client_addr = client_writer.get_extra_info('peername')
    print(f"[PROXY] New connection from {client_addr}")

    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
        print(f"[PROXY] Successfully connected to upstream server at {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    except ConnectionRefusedError:
        print(f"[ERROR] Connection to upstream server {UPSTREAM_HOST}:{UPSTREAM_PORT} was refused. Is it running?")
        client_writer.close()
        await client_writer.wait_closed()
        return
    except Exception as e:
        print(f"[ERROR] Failed to connect to upstream server: {e}")
        client_writer.close()
        await client_writer.wait_closed()
        return

    task_c2s = asyncio.create_task(forward_client_to_server(client_reader, upstream_writer))
    task_s2c = asyncio.create_task(forward_server_to_client_with_fix(upstream_reader, client_writer))

    await asyncio.gather(task_c2s, task_s2c)
    print(f"[PROXY] Connection from {client_addr} closed.")


async def main():

    global UPSTREAM_HOST, UPSTREAM_PORT

    parser = argparse.ArgumentParser(description="A real-time fixing proxy for Claude Code.")
    parser.add_argument('--listen-host', default=LISTEN_HOST, help=f"Host to listen on (default: {LISTEN_HOST})")
    parser.add_argument('--listen-port', type=int, default=LISTEN_PORT, help=f"Port to listen on (default: {LISTEN_PORT})")

    parser.add_argument('--upstream-host', default=UPSTREAM_HOST, help=f"Upstream server host (default: {UPSTREAM_HOST})")
    parser.add_argument('--upstream-port', type=int, default=UPSTREAM_PORT, help=f"Upstream server port (default: {UPSTREAM_PORT})")
    args = parser.parse_args()

    UPSTREAM_HOST = args.upstream_host
    UPSTREAM_PORT = args.upstream_port

    server = await asyncio.start_server(
        handle_client_connection, args.listen_host, args.listen_port
    )

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"--- Claude Code Fixing Proxy ---")
    print(f"Listening on: {addrs}")
    print(f"Forwarding to: {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    print("---------------------------------")
    print("Now, connect your Claude Code client to this proxy instead of the original port.")
    print("Press Ctrl+C to stop.")

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down.")