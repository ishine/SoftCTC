import torch
import numpy as np
import importlib
import sys

from soft_ctc.models import BatchConnections

static_opencl_path = "soft_ctc.libs.opencl.soft_ctc_opencl"

try:
    soft_ctc_opencl = importlib.import_module(static_opencl_path)
except:
    print("Error: Unable to load precompiled OpenCL SoftCTC library.", file=sys.stderr)
    soft_ctc_opencl = None


class SoftCTCLoss(torch.autograd.Function):
    def __init__(self, norm_step=10, zero_infinity=True, use_torch_buffers=True):
        self._norm_step = norm_step
        self._zero_infinity = zero_infinity
        self._use_torch_buffers = use_torch_buffers

        self._gpu_ctx = None

    def __call__(self, logits, connections: BatchConnections, labels):
        if self._gpu_ctx is None:
            self.init_gpu_ctx(logits.dtype)

        return self.apply(logits, connections, labels, self._gpu_ctx, self._use_torch_buffers,
                          self._norm_step, self._zero_infinity)

    def init_gpu_ctx(self, dtype=torch.float, use_static_compilation=True, use_sync_native=False):
        if soft_ctc_opencl is None:
            self._gpu_ctx = None
            return
        if dtype == torch.float:
            self._gpu_ctx = soft_ctc_opencl.CTCOpenCLFloat(False)
        else:
            self._gpu_ctx = soft_ctc_opencl.CTCOpenCLDouble(False)

    @staticmethod
    def forward(ctx, logits, connections: BatchConnections, labels, gpu_ctx, use_torch_buffers, norm_step=10, zero_infinity=False):
        logits_swap = logits.permute(2, 0, 1).contiguous()
        labels_int = labels.type(torch.IntTensor)

        if use_torch_buffers:
            grads = torch.zeros(logits_swap.shape, dtype=logits.dtype, device="cpu")
            loss = torch.zeros(logits_swap.shape[1], dtype=logits.dtype, device="cpu")
        else:
            if logits.dtype == torch.double:
                numpy_type = np.float64
            elif logits.dtype == torch.float:
                numpy_type = np.float32
            else:
                print("Error: Data cannot be converted to numpy.", file=sys.stderr)
                return None

            grads = np.zeros(logits_swap.shape, dtype=numpy_type, order='C')
            loss = np.zeros(logits_swap.shape[1], dtype=numpy_type, order='C')

        if gpu_ctx is None:
            print("Error: Precompiled OpenCL SoftCTC library is not loaded. Unable to run SoftCTC.", file=sys.stderr)
        else:
            if use_torch_buffers:
                result = gpu_ctx.calcCTCTorch(grads, loss, connections.forward.to("cpu"), connections.forward_start.to("cpu"), connections.forward_end.to("cpu"), connections.backward.to("cpu"), connections.backward_start.to("cpu"), connections.backward_end.to("cpu"), logits_swap.to("cpu"), labels_int, norm_step, zero_infinity)
            else:
                result = gpu_ctx.calcCTC(grads, loss, connections.forward.numpy(), connections.forward_start.numpy(), connections.forward_end.numpy(), connections.backward.numpy(), connections.backward_start.numpy(), connections.backward_end.numpy(), logits_swap.numpy(), labels_int.numpy(), norm_step, zero_infinity)

        if use_torch_buffers:
            ctx.grads = grads.permute(1, 2, 0).to(logits.device)
            return loss.to(logits.device)
        else:
            ctx.grads = torch.from_numpy(grads).permute(1, 2, 0)
            return torch.from_numpy(loss)

    @staticmethod
    def backward(ctx, ll_forward):
        grads = ctx.grads
        del ctx.grads

        return grads, None, None, None, None, None, None, None
