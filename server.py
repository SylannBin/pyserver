#!/usr/bin/python3.6
import mimetypes
import os
import socket
import typing
from queue import Queue, Empty
from threading import Thread
from request import Request
from response import Response
from pprint import PrettyPrinter


class HTTPServer:
    def __init__(
        self,
        host: str="127.0.0.1",
        port: int=8080,
        worker_count: int=16
    ) -> None:
        self.host = host
        self.port = port
        self.worker_count = worker_count
        self.worker_backlog = self.worker_count * 8
        self.connection_queue = Queue(self.worker_backlog)

    def start(self) -> None:
        workers = []
        for __ in range(self.worker_count):
            worker = HTTPWorker(self.connection_queue)
            worker.start()
            workers.append(worker)

        with socket.socket() as server_sock:
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((self.host, self.port))
            server_sock.listen(0)
            print(f"Listening on {self.host}:{self.port}...")

            while True:
                try:
                    self.connection_queue.put(server_sock.accept())
                except KeyboardInterrupt:
                    break

        for worker in workers:
            worker.stop()

        for worker in workers:
            worker.join(timeout=30)


class HTTPWorker(Thread):
    def __init__(self, connection_queue: Queue) -> None:
        super().__init__(daemon=True)
        self.connection_queue = connection_queue
        self.running = True

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        self.running = True
        while self.running:
            try:
                client_sock, client_addr = self.connection_queue.get(timeout=1)
            except Empty:
                continue
            try:
                self.handle_client(client_sock, client_addr)
            except Exception as e:
                print(f"Unhandled error: {e}")
                continue
            finally:
                self.connection_queue.task_done()

    def handle_client(
        self,
        client_sock: socket.socket,
        client_addr: typing.Tuple[str, int]
    ) -> None:
        print(f"New connection from {client_addr}...")
        with client_sock:
            try:
                req = Request.from_socket(client_sock)
                if "100-continue" in req.headers.get("expect", ""):
                    Response.from_status_code(100).send(client_sock)

                try:
                    content_len = int(req.headers.get("content-length", "0"))
                except ValueError:
                    content_len = 0

                if content_len:
                    body = req.body.read(content_len)
                    print("Request body", body)

                if req.method != 'GET':
                    Response.from_status_code(405).send(client_sock)
                    return

                serve_file(client_sock, req.path)
            except Exception as e:
                print(f"Failed to parse request: {e}")
                Response.from_status_code(404).send(client_sock)


def serve_file(sock: socket.socket, path: str, root: str="www") -> None:
    """Given a socket and the relative path to a file (relative to
    SERVER_SOCK), send that file to the socket if it exists.  If the
    file doesn't exist, send a "404 Not Found" response.
    """
    root_path = os.path.abspath(root)

    if path == "/":
        path = "/index.html"

    abspath = os.path.normpath(os.path.join(root_path, path.lstrip("/")))
    if not abspath.startswith(root_path):
        Response.from_status_code(404).send(sock)
        return

    try:
        with open(abspath, "rb") as f:
            content_type, encoding = mimetypes.guess_type(abspath)
            if content_type is None:
                content_type = "application/octet-stream"
            if encoding is not None:
                content_type += f"; charset={encoding}"

            res = Response(status="200 OK", body=f)
            res.headers.add("content-type", content_type)
            res.send(sock)
            return
    except FileNotFoundError:
        Response.from_status_code(404).send(sock)
        return


if __name__ == '__main__':
    server = HTTPServer()
    server.start()
