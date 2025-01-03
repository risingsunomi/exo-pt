import traceback
from aiofiles import os as aios
from transformers import AutoTokenizer, AutoProcessor
from exo.download.hf.hf_helpers import get_local_snapshot_dir
from exo.helpers import DEBUG

async def resolve_tokenizer(model_id: str):
  local_path = await get_local_snapshot_dir(model_id)
  if DEBUG >= 2: print(f"Checking if local path exists to load tokenizer from local {local_path=}")
  try:
    if await aios.path.exists(local_path):
      if DEBUG >= 2: print(f"Resolving tokenizer for {model_id=} from {local_path=}")
      return await _resolve_tokenizer(local_path)
  except:
    if DEBUG >= 5: print(f"Local check for {local_path=} failed. Resolving tokenizer for {model_id=} normally...")
    if DEBUG >= 5: traceback.print_exc()
  return await _resolve_tokenizer(model_id)

async def _resolve_tokenizer(model_id_or_local_path: str):
  try:
    if DEBUG >= 4: print(f"Trying AutoProcessor for {model_id_or_local_path}")
    if "Mistral-Large" in str(model_id_or_local_path):
      use_fast = True
    else:
      use_fast = False
    processor = AutoProcessor.from_pretrained(model_id_or_local_path, use_fast=use_fast)
    if not hasattr(processor, 'eos_token_id'):
      processor.eos_token_id = getattr(processor, 'tokenizer', getattr(processor, '_tokenizer', processor)).eos_token_id
    if not hasattr(processor, 'encode'):
      processor.encode = getattr(processor, 'tokenizer', getattr(processor, '_tokenizer', processor)).encode
    if not hasattr(processor, 'decode'):
      processor.decode = getattr(processor, 'tokenizer', getattr(processor, '_tokenizer', processor)).decode
    return processor
  except Exception as e:
    if DEBUG >= 4: print(f"Failed to load processor for {model_id_or_local_path}. Error: {e}")
    if DEBUG >= 4: print(traceback.format_exc())

  try:
    if DEBUG >= 4: print(f"Trying AutoTokenizer for {model_id_or_local_path}")
    return AutoTokenizer.from_pretrained(model_id_or_local_path)
  except Exception as e:
    if DEBUG >= 4: print(f"Failed to load tokenizer for {model_id_or_local_path}. Falling back to tinygrad tokenizer. Error: {e}")
    if DEBUG >= 4: print(traceback.format_exc())

  raise ValueError(f"[TODO] Unsupported model: {model_id_or_local_path}")
