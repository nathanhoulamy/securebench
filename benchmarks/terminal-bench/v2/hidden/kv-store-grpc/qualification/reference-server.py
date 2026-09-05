import grpc
import kv_store_pb2_grpc
from kv_store_pb2 import GetValResponse, SetValResponse
from concurrent import futures


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self.kv_dict: dict[str, int] = {}

    def GetVal(self, request, unused_context) -> GetValResponse:
        return GetValResponse(val=self.kv_dict.get(request.key, 0))

    def SetVal(self, request, unused_context) -> SetValResponse:
        self.kv_dict[request.key] = request.value
        return SetValResponse(val=request.value)


if __name__ == "__main__":
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()
