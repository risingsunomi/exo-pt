"""
Test of pytorch based llama3 models
full layer run
"""

from pathlib import Path
import torch
from huggingface_hub import snapshot_download

import torchtune.generation as ttg
from torchtune.models import llama3
from torchtune.data import Message

from transformers import AutoTokenizer

from exo.inference.torch.models.llama3 import ShardedLlamaModel
from exo.inference.shard import Shard

from exo.inference.torch.models.llm_utils import (load_model_config, load_model_weights_torchtune, check_weights)

# MODEL_NAME = "unsloth/Llama-3.2-3B-Instruct"
MODEL_NAME = "meta-llama/Llama-3.2-1B-Instruct"
TEMP = 0.0
TOP_K = 35
MAX_NEW_TOKENS = 100


def main(model, prompt: str, device: torch.device = torch.device("cpu")):
  messages = [{
    "role": "assistant",
    "content": "",
  }, {
    "role": "user",
    "content": prompt,
  }]

  text = llama_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
  tok_out = llama_tokenizer([text], return_tensors="pt")
  tokens = tok_out.input_ids.to(device=device)

  # messages = []
  # messages.extend([
  #   Message(role="system", content="You are a helpful and creative AI assistant."),
  #   Message(role="user", content=prompt),
  #   # Empty assistant message to kick-start generation
  #   Message(role="assistant", content=""),
  # ])

  # tokenizer_out = llama_tokenizer({"messages": messages}, inference=True)
  # tokens = torch.tensor([tokenizer_out["tokens"]], dtype=torch.int, device=device)

  generated_tokens = tokens.clone()

  print(f"tokens: {tokens}")

  _, logits = model.generate(tokens=tokens)

  tokens = ttg.sample(
    logits=logits[:, -1].clone(),
    temperature=TEMP,
    top_k=TOP_K,
  )

  print(f"tokens: {tokens}")

  for i in range(MAX_NEW_TOKENS - 1):
    print(f"gen #{i}")

    if tokens.item() == llama_tokenizer.eos_token_id:
      # if tokens.item() in llama_tokenizer.stop_tokens:
      print("stop token hit!")
      break

    _, logits = model.generate(tokens=tokens)

    tokens = ttg.sample(
      logits=logits[:, -1].clone(),
      temperature=TEMP,
      top_k=TOP_K,
    )

    print(f"tokens: {tokens}")

    generated_tokens = torch.cat([generated_tokens, tokens], dim=-1)
    print(f"generated_tokens: {generated_tokens}")

    if not model.model.caches_are_enabled():
      tokens = generated_tokens.clone()

  print(f"\n\n[resp from model]\n\n{llama_tokenizer.decode(generated_tokens.tolist()[0])}\n\n\n")


def normal_full(model, user_prompt: str, device: torch.device = torch.device("cpu")):
  # Tokenize input text
  messages = []
  messages.extend([
    Message(role="system", content="You are a helpful and creative AI assistant."),
    Message(role="user", content=user_prompt),
    # Empty assistant message to kick-start generation
    Message(role="assistant", content=""),
  ])

  tokenizer_out = llama_tokenizer({"messages": messages}, inference=True)
  prompt = torch.tensor(tokenizer_out["tokens"], dtype=torch.int, device=device)
  print(f"tokens prompt: {prompt}")
  print(f"pad_id: {llama_tokenizer.pad_id}")

  generated_tokens, _ = ttg.generate(
    model=model.model,
    prompt=prompt,
    max_generated_tokens=MAX_NEW_TOKENS,
    pad_id=llama_tokenizer.pad_id,
    temperature=TEMP,
    top_k=TOP_K,
    stop_tokens=llama_tokenizer.stop_tokens,
  )

  generated_tokens = generated_tokens[:, -MAX_NEW_TOKENS:].tolist()

  print(f"generated_tokens: {generated_tokens}")

  print(f"\n\n[resp from model]\n\n{llama_tokenizer.decode(generated_tokens[0])}\n\n\n")


if __name__ == "__main__":
  prompt = "Tell me a joke."
  # prompt = "What is the meaning of exo?"
  # prompt = "Tell me a short 4 line haiku"
  # prompt = "In a single word only, what is the last name of the current president of the USA?"

  # Get the path to the model files from the Hugging Face cache
  cache_dir = Path(snapshot_download(MODEL_NAME))
  print(f"Cache directory: {cache_dir}")

  # Load model configuration
  config = load_model_config(cache_dir/"config.json")

  print(f"current config\n{config}")

  # Setup shard
  n_layers = int(config["num_layers"])
  shard_1 = Shard(
    model_id=MODEL_NAME,
    start_layer=0,
    end_layer=n_layers - 1,
    n_layers=n_layers,
  )

  # Initialize tokenizer
  # llama_tokenizer_path = f"{cache_dir}/original/tokenizer.model"
  # llama_tokenizer = llama3.llama3_tokenizer(path=llama_tokenizer_path)
  llama_tokenizer = AutoTokenizer.from_pretrained(cache_dir)

  # Initialize LlamaModel with config and tokenizer
  device = torch.device("cuda")
  # device = torch.device("cpu")
  shard_model_1 = ShardedLlamaModel(
    config=config,
    shard=shard_1,
    device=device,
    use_cache=True,
    max_generated_tokens=MAX_NEW_TOKENS,
  )

  print(f"\nshard_model_1: {shard_model_1}")

  load_model_weights_torchtune(cache_dir, shard_1, shard_model_1)

  main(shard_model_1, prompt, device)
  # normal_full(shard_model_1, prompt, device)