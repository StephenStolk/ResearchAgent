from dotenv import load_dotenv
load_dotenv()

from backend.agent import app


question = input("What do you want me to research on?")

result = app.invoke({
    "messages": [
        {
            "role": "user",
            "content": question
        }
    ]
})

print("\n\n==============================")
print("FINAL ANSWER")
print("==============================\n")

print(result["messages"][-1].content)
