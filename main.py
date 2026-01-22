from rlm import RLM
from rlm.logger import RLMLogger
from dotenv import load_dotenv
import os

load_dotenv()

logger = RLMLogger(log_dir="./logs")

def main():
    with open("./snake/snake.c", "r") as f:
        context = f.read()

    rlm = RLM(
        backend="openai",
        backend_kwargs={
            "api_key": os.getenv("OPENAI_API_KEY"),
            "model_name": "gpt-5-nano"
        },
        environment_kwargs={},
        environment="local",
        max_depth=1,
        logger=logger,
        max_iterations=10,
        verbose=True,
    )

    query = "Re-write this code from C to rust"
    #query = "What is the max size of the snake?"
    prompt = f"Context: {context}\n\nQuery: {query}\n\n"
    
    result = rlm.completion(prompt=prompt, root_prompt=query)

if __name__ == "__main__":
    main()