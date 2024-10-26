"""
Test of pytorch based llama3 model
"""
from pathlib import Path

import torch
import torchtune.generation as ttg
from transformers import AutoTokenizer
from huggingface_hub import snapshot_download
from safetensors.torch import load_file as load_safetensors
from exo.inference.torch.models.llm_utils import load_model_config, select_next_token
from exo.inference.torch.models.llama3 import LlamaModel, KVCache
from exo.inference.shard import Shard

MODEL_NAME = "unsloth/Llama-3.2-1B-Instruct"
TEMP=0.7
TOP_K=35
TOP_P=0.9


def test_generation(model, tokenizer, text, max_length=10):
  """
  Test the generation capabilities of the LlamaModel with sample text.
  """
  # Tokenize input text
  prompt = tokenizer.apply_chat_template([
    {
      "role": "user",
      "content": text
    }
  ], tokenize=False, add_generation_prompt=True)
  
  print(f"prompt: {prompt}")

  inputs = tokenizer(prompt, return_tensors="pt")
  input_ids = inputs.get("input_ids")
  attention_mask = inputs.get("attention_mask")

  print(f"input_ids: {input_ids}")
  print(f"attention_mask: {attention_mask}")

  # Initialize KVCache for caching
  past_kv_cache = KVCache(
    batch_size=input_ids.size(0),
    max_seq_len=model.max_position_embeddings,
    num_heads=model.num_heads,
    head_dim=model.head_dim,
    dtype=input_ids.dtype
  )

  # Start with initial input_ids
  generated_ids = input_ids.clone()

  # Generate tokens step-by-step
  for _ in range(max_length):
    with torch.no_grad():
      logits, _, past_kv_cache = model(
        generated_ids,
        attention_mask=attention_mask,
        past_kv_cache=past_kv_cache
      )

    # Select next token using logits
    #next_token = select_next_token(logits, top_k=TOP_K, top_p=TOP_P, temperature=TEMP, use_max=False)
    next_token = ttg.sample(logits[:, -1, :].clone().float(), temperature=TEMP, top_k=TOP_K).squeeze(-1)
    print(f"next_token: {next_token}")

    # Update generated_ids
    generated_ids = torch.cat([generated_ids, next_token.unsqueeze(0)], dim=1)
    print(f"generated_ids: {generated_ids}")

    # Check for EOS token
    if next_token.item() == tokenizer.eos_token_id:
      break

  # Decode generated text
  generated_text = tokenizer.decode(generated_ids[0], skip_special_tokens=True)
  print(f"\nPrompt: {text}")
  print(f"\nGenerated Response: {generated_text}")

if __name__ == "__main__":
  print("\nTesting generation:")
  # Get the path to the model files from the Hugging Face cache
  cache_dir = Path(snapshot_download(MODEL_NAME))
  print(f"Cache directory: {cache_dir}")

  # Load model configuration
  config = load_model_config(cache_dir / "config.json")

  print(f"current config\n{config}")

  # Setup shard
  shard = Shard(
    model_id=MODEL_NAME,
    start_layer=0,
    end_layer=int(config["num_hidden_layers"]) - 1,
    n_layers=int(config["num_hidden_layers"])
  )

  # Initialize tokenizer
  tokenizer = AutoTokenizer.from_pretrained(cache_dir)

  # Initialize LlamaModel with config and tokenizer
  model = LlamaModel(config, shard)

  # Load weights from safetensors files in the cache directory
  safetensors_files = list(cache_dir.glob("*.safetensors"))
  if not safetensors_files:
    raise FileNotFoundError("No safetensors files found in the cache directory.")

  # Load weights from each found safetensors file
  for safetensor_file in safetensors_files:
    print(f"Loading weights from: {safetensor_file}")
    state_dict = load_safetensors(safetensor_file)
    model.load_state_dict(state_dict, strict=False)

  model.eval()  # Set the model to evaluation mode

  # Sample text for testing
  test_text = "What color is a red apple?"

  test_generation(model, tokenizer, test_text)
