# experimental, based off of tinygrad/inference.py
# utilizing pytorch FSDP for sharding
# look into shard being optional for the inferece

import os
import shutil
import json
import torch
import numpy as np
from pathlib import Path
from typing import Optional, Callable, Tuple
from transformers import AutoTokenizer, AutoModelForCausalLM
from exo.inference.shard import Shard
from exo.inference.inference_engine import InferenceEngine
from exo.inference.pytorch.helpers import download_files
from exo.inference.pytorch.model.llama import ShardedLLAMAModel

# Default settings
TEMPERATURE = 0.7
TOP_K = 50

class PyTorchDynamicShardInferenceEngine(InferenceEngine):
    def __init__(self, debug: bool = False):
        self.shard = None
        self.debug = debug

    async def infer_prompt(
            self, 
            request_id: str, 
            shard: Optional[Shard], 
            prompt: str, 
            inference_state: Optional[str] = None) -> Tuple[np.ndarray, str, bool]:
        await self.ensure_shard(shard)

        input_ids = self.tokenizer.encode(prompt, return_tensors="pt").to(self.model.device)
        
        # Continue the sequence if inference state exists
        past_key_values = None
        if inference_state:
            past_key_values = self._load_kv_cache(json.loads(inference_state).get("past_key_values"))

        output, past_key_values = self.model(input_ids, past_key_values=past_key_values)

        if self.shard.is_last_layer():
            logits = self._apply_generation_settings(output, TEMPERATURE, TOP_K)
            next_token = torch.argmax(logits[:, -1, :], dim=-1)
            output_data = np.array([next_token.item()])
            is_eos = next_token.item() == self.tokenizer.eos_token_id
        else:
            output_data = output.cpu().numpy()
            is_eos = False

        new_inference_state = json.dumps({"past_key_values": self._save_kv_cache(past_key_values)})

        if self.debug:
            print(f"Infer Prompt Debug - Request ID: {request_id}, Output: {output_data}, EOS: {is_eos}")

        return output_data, new_inference_state, is_eos

    async def infer_tensor(
            self, 
            request_id: str, 
            shard: Optional[Shard], 
            input_data: np.ndarray, 
            inference_state: Optional[str] = None) -> Tuple[np.ndarray, str, bool]:
        await self.ensure_shard(shard)

        input_tensor = torch.tensor(input_data).unsqueeze(0).to(self.model.device)
        
        # Continue the sequence if inference state exists
        past_key_values = None
        if inference_state:
            past_key_values = self._load_kv_cache(json.loads(inference_state).get("past_key_values"))

        output, past_key_values = self.model(input_tensor, past_key_values=past_key_values)

        if self.shard.is_last_layer():
            logits = self._apply_generation_settings(output, TEMPERATURE, TOP_K)
            next_token = torch.argmax(logits[:, -1, :], dim=-1)
            output_data = np.array([next_token.item()])
            is_eos = next_token.item() == self.tokenizer.eos_token_id
        else:
            output_data = output.cpu().numpy()
            is_eos = False

        new_inference_state = json.dumps({"past_key_values": self._save_kv_cache(past_key_values)})

        if self.debug:
            print(f"Infer Tensor Debug - Request ID: {request_id}, Output: {output_data}, EOS: {is_eos}")

        return output_data, new_inference_state, is_eos

    def _apply_generation_settings(self, logits, temperature, top_k):
        logits = logits / temperature
        if top_k > 0:
            top_k_values, top_k_indices = torch.topk(logits, top_k, dim=-1)
            logits = logits.scatter(1, top_k_indices, top_k_values)
        return logits

    def _load_kv_cache(self, past_key_values_list):
        if past_key_values_list is None:
            return None
        return [torch.tensor(kv, device=self.model.device) for kv in past_key_values_list]

    def _save_kv_cache(self, past_key_values):
        return [kv.cpu().tolist() for kv in past_key_values]

    async def ensure_shard(self, shard: Optional[Shard]):
        if self.shard == shard:
            return

        model_path = Path(f".cache/{shard.model_id}")
        if not model_path.exists():
            os.makedirs(model_path, exist_ok=True)
        else:
            shutil.rmtree(model_path)
            os.makedirs(model_path)

            if shard.model_id.lower().find("llama3-8b-sfr") != -1:
                num_files = 4
                urls = [
                    f"https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/resolve/main/model-{(i+1):05d}-of-{num_files:05d}.safetensors"
                    for i in range(num_files)
                ]
                urls.extend([
                    "https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/resolve/main/config.json",
                    "https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/raw/main/model.safetensors.index.json",
                    "https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/resolve/main/special_tokens_map.json",
                    "https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/resolve/main/tokenizer.json",
                    "https://huggingface.co/mlx-community/Meta-Llama-3-8B-Instruct/resolve/main/tokenizer_config.json"
                ])
                
                output_paths = [
                    model_path / f"model-{(i+1):05d}-of-{num_files:05d}.safetensors"
                    for i in range(num_files)
                ]
                output_paths.extend([
                    model_path / "config.json",
                    model_path / "model.safetensors.index.json",
                    model_path / "special_tokens_map.json",
                    model_path / "tokenizer.json",
                    model_path / "tokenizer_config.json"
                ])

                await download_files(urls, output_paths)
            else:
                raise ValueError(f"Unsupported model: {shard.model_id}")

        # Load model and tokenizer from the downloaded files
        model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32)
        self.model = ShardedLLAMAModel(model, shard)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        self.shard = shard

    def set_on_download_progress(self, on_download_progress: Callable[[int, int], None]):
        # This method can be implemented if progress tracking is needed
        pass