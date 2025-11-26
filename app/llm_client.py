import json
import re
from typing import Any, Dict

import httpx

from .config import settings

# AiPipe proxies OpenAI's "responses" endpoint:
# See: https://github.com/sanand0/aipipe
AIPIPE_URL = "https://aipipe.org/openai/v1/responses"


async def ask_llm_for_answer(quiz_context: str) -> Dict[str, Any]:
    """
    Uses AiPipe API instead of OpenAI directly.

    Expects AiPipe to call an OpenAI-compatible model and return a JSON
    where the assistant's text content itself is a JSON string like:
      {"answer": ...}

    We then parse and return that dict.
    """

    full_prompt = f"""You are an expert data analyst solving quiz questions. You will receive the COMPLETE content of a web page that contains:
1. A question to answer
2. All necessary data (already fetched and provided below)
3. Instructions on how to submit your answer

CRITICAL RULES:
- The content below is COMPLETE - you do NOT need to visit URLs or access external resources
- READ CAREFULLY: Find the EXACT question being asked (look for question marks, numbered items like "Q1.", "Question:", etc.)
- ANALYZE the data provided thoroughly
- PAY ATTENTION to what format is requested (number, string, sum, count, specific value, etc.)
- If there are data files (CSV, JSON, etc.), analyze them to compute the answer
- If the question mentions "secret", look for patterns or hidden values in the data
- If audio files are mentioned but can't be transcribed, state that clearly
- COMPUTE the exact answer based on the data provided
- Return ONLY a JSON object: {{"answer": <your_answer>}}
- The answer can be a number, string, boolean, array, or object as needed
- DO NOT explain your reasoning, just return the JSON with the answer
- DO NOT say you cannot access content - everything is provided below

COMMON QUESTION PATTERNS TO LOOK FOR:
- "What is the sum of..." → Add up the numbers
- "What is the secret..." → Look for hidden patterns, specific column values, or encoded data
- "How many..." → Count items
- "What is the value of..." → Find specific value
- "List all..." → Return an array
- "Download file..." → The file content is already provided below

====================
QUIZ CONTENT:
====================

{quiz_context}

====================
YOUR RESPONSE:
====================

Now analyze the content above carefully:
1. Identify the EXACT question being asked
2. Find the relevant data (tables, numbers, text patterns)
3. Compute the answer precisely
4. Return ONLY this JSON format: {{"answer": <computed_answer>}}

Remember: 
- If the question asks for a number, return a number (not a string)
- If it asks for text, return a string
- If it asks for multiple values, return an array or object
- Be precise and accurate based on the data provided above"""

    payload = {
        "model": settings.llm_model,  # e.g. "gpt-4o-mini"
        "input": full_prompt,
    }

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(AIPIPE_URL, json=payload, headers=headers, timeout=90)
            response.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"AiPipe HTTP error: {e}") from e

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AiPipe returned invalid JSON: {response.text}") from e

    # Expected AiPipe/OpenAI "responses" format:
    # {
    #   "output": [
    #     {
    #       "role": "assistant",
    #       "content": [
    #         { "text": "{ \"answer\": 123 }" }
    #       ]
    #     }
    #   ]
    # }
    try:
        outputs = data.get("output", [])
        if not outputs:
            raise KeyError("No output in AiPipe response")
        
        first = outputs[0]
        contents = first.get("content", [])
        
        # Find the first content part with "text"
        text_parts = [c.get("text") for c in contents if c.get("text")]
        if not text_parts:
            raise KeyError("No text content found in AiPipe response.")
        
        content_text = text_parts[0].strip()
        
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"Unexpected AiPipe response format: {json.dumps(data, indent=2)}"
        ) from e

    # Parse the model's response
    content_text = content_text.strip()
    
    # Remove markdown code blocks if present
    if content_text.startswith("```json"):
        content_text = content_text[7:]
    elif content_text.startswith("```"):
        content_text = content_text[3:]
    
    if content_text.endswith("```"):
        content_text = content_text[:-3]
    
    content_text = content_text.strip()
    
    # Sometimes LLMs add explanation before or after JSON
    # Try to extract just the JSON object
    json_match = re.search(r'\{[^{}]*"answer"[^{}]*\}', content_text, re.DOTALL)
    if json_match:
        content_text = json_match.group(0)
    
    try:
        answer_obj = json.loads(content_text)
    except json.JSONDecodeError as exc:
        # Try one more time with more aggressive JSON extraction
        json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
        all_json = re.findall(json_pattern, content_text, re.DOTALL)
        
        for potential_json in all_json:
            try:
                obj = json.loads(potential_json)
                if "answer" in obj:
                    answer_obj = obj
                    break
            except json.JSONDecodeError:
                continue
        else:
            raise ValueError(
                f"LLM did not return valid JSON. Raw response:\n{content_text}"
            ) from exc

    if "answer" not in answer_obj:
        raise ValueError(
            f"LLM JSON missing 'answer' key. Got: {json.dumps(answer_obj, indent=2)}"
        )

    return answer_obj