# experimental, based off of tinygrad/inference.py

import numpy as np
import torch
import numpy as np
import json
from typing import Optional, Callable, Tuple
from transformers import AutoTokenizer
from exo.inference.shard import Shard
from exo.inference.inference_engine import InferenceEngine
from exo.inference.pytorch.model.hf import ShardedHuggingFaceModel
from exo.helpers import DEBUG

class PyTorchDynamicShardInferenceEngine(InferenceEngine):
    """
    PyTorch Dynamic Shard Inference Engine for performing model inference with sharded models.
    """

    def __init__(self):
        """
        Initialize the inference engine.

        Args:
            debug (bool): If True, enables debug logging. Defaults to False.
        """
        self.shard = None
        self.model = None
        self.tokenizer = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    async def infer_prompt(
        self, 
        request_id: str, 
        shard: Optional[Shard] = None, 
        prompt: str = "", 
        image_str: Optional[str] = None, 
        inference_state: Optional[str] = None
    ) -> Tuple[np.ndarray, str, bool]:
        if DEBUG >= 2:
            print("infer_prompt called")

        await self.ensure_shard(shard)

        inference_state = json.loads(inference_state) if inference_state else ""
        tokens = self.tokenizer.encode(prompt, return_tensors="pt")

        if DEBUG >= 2:
            print(f"tokens: {tokens}\n")

        output_data, inference_state = self.model.forward_layers(
            tokens,
            inference_state
        )

        is_finished = output_data[-1] == self.tokenizer.eos_token_id and output_data.size == 1

        if DEBUG >= 2:
            print(f"output_data: {output_data}\n")
            print(f"output_data.size {output_data.size}\n")
            print(f"output_data.item() {output_data.item()}")
            print(f"inference_state: {inference_state}")
            print(f"finished: {is_finished}")
            print(f"self.tokenizer.eos_token_id {self.tokenizer.eos_token_id}")
            print(f"output_data[-1] {output_data[-1]}")
            print(f"output_data.item() in [self.tokenizer.eos_token_id]: {output_data.item() in [self.tokenizer.eos_token_id]}")

        return (
            output_data,
            json.dumps(inference_state),
            is_finished
        )

    async def infer_tensor(
        self, 
        request_id: str, 
        shard: Shard, 
        input_data: np.ndarray, 
        inference_state: Optional[str] = None) -> Tuple[np.ndarray, str, bool]:

        in_tensor = torch.tensor(input_data)
        inference_state = json.loads(inference_state) if inference_state else ""

        if DEBUG >= 2:
            print("infer_tensor called")
            print(f"input_data: {input_data}\n")
            print(f"in_tensor: {in_tensor}\n")

        await self.ensure_shard(shard)

        output_data, inference_state = self.model.forward_layers(
            in_tensor,
            inference_state
        )

        is_finished = output_data[-1] == self.tokenizer.eos_token_id and output_data.size == 1

        if DEBUG >= 2:
            print(f"output_data: {output_data}\n")
            print(f"output_data.size {output_data.size}\n")
            print(f"output_data.item() {output_data.item()}")
            print(f"inference_state: {inference_state}")
            print(f"finished: {is_finished}")
            print(f"self.tokenizer.eos_token_id {self.tokenizer.eos_token_id}")
            print(f"output_data[-1] {output_data[-1]}")
            print(f"output_data.item() in [self.tokenizer.eos_token_id]: {output_data.item() in [self.tokenizer.eos_token_id]}")

        return (
            output_data,
            json.dumps(inference_state),
            is_finished
        )

    async def ensure_shard(self, shard: Optional[Shard]):
        """
        Ensure the model shard is loaded and ready for inference.

        Args:
            shard (Optional[Shard]): Shard information for the model.
        """
        if self.shard == shard:
            return

        if DEBUG >= 2:
            print(f"Loading new shard: {shard}")

        self.model = ShardedHuggingFaceModel(shard)
        self.tokenizer = AutoTokenizer.from_pretrained(
            shard.model_id,
            add_eos_token=True,
            use_fast=True
        )
        self.shard = shard

        if DEBUG >= 2:
            print(f"Shard loaded successfully: {shard}")