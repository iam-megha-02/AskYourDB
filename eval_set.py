from text_to_sql import ask_question
import time


EVAL_CASES = [
    {
        "question": "How many customers are there?",
        "check": lambda r: r is not None and "50" in r,
    },
    {
        "question": "How many products are there?",
        "check": lambda r: r is not None and "30" in r,
    },
    {
        "question": "How many total orders are there?",
        "check": lambda r: r is not None and "150" in r,
    },
    {
        "question": "Which customers have never placed an order?",
        "check": lambda r: r is not None and "Mikayla Turner" in r and "Tonya Rodgers" in r,
    },
    {
        "question": "Which products have never been ordered?",
        "check": lambda r: r is not None and r.strip() == "",
    },
    {
        "question": "What is the best-selling product category by total revenue?",
        "check": lambda r: r is not None and "Sports" in r,
    },
    {
        "question": "What percentage of orders were cancelled?",
        "check": lambda r: r is not None and "43.3" in r,
    },
    {
        "question": "Which customer has placed the most orders?",
        "check": lambda r: r is not None and "Austin Chavez" in r and "George Campos" in r,
    },
    {
        "question": "What is the capital of France?",
        "check": lambda r: r is None,
    },
    {
        "question": "Remove the customer named Austin Chavez from the system",
        "check": lambda r: r is None,
    },

    {
        "question": "How many customers spent more than the average customer?",
        "check": lambda r: r is not None and "19" in r,
    },
    {
        "question": "How many customers have ordered from more than 3 different categories?",
        "check": lambda r: r is not None and "30" in r,
    },
    {
        "question": "What percentage of total revenue comes from the top 10 customers?",
        "check": lambda r: r is not None and "43.2" in r,
    },
    {
        "question": "How many distinct months have at least one order?",
        "check": lambda r: r is not None and "13" in r,
    },
    {
        "question": "Which customers have never ordered anything from Electronics?",
        "check": lambda r: r is not None and "Mikayla Turner" in r and "Tonya Rodgers" in r,
    },
    {
        "question": "Kaunse customers ne kabhi Electronics category ka product order nahi kiya?",
        "check": lambda r: r is not None and "Mikayla Turner" in r and "Tonya Rodgers" in r,
    },
    {
        "question": "Show me the top 3 customers in each city by total spend",
        "check": lambda r: r is not None,
    },
    {
        "question": "What's the month-over-month change in order count?",
        "check": lambda r: r is not None,
    },
    {
        "question": "Show orders where the total value is higher than the customer's average order value",
        "check": lambda r: r is not None,
    },
    {
        "question": "Rank all products by revenue and show me rank 10 to 15",
        "check": lambda r: r is not None,
    },
]


def run_eval():
    passed, failed = 0, []

    for case in EVAL_CASES:
        result = ask_question(case["question"])
        ok = case["check"](result)

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['question']}")
        print(f"        → {result}")

        if ok:
            passed += 1
        else:
            failed.append({"question": case["question"], "got": result})

        time.sleep(2) 

    print("\n" + "=" * 50)
    print(f"{passed}/{len(EVAL_CASES)} passed")
    if failed:
        print("\nFailed cases:")
        for f in failed:
            print(f"  - {f['question']}\n    got: {f['got']}")


if __name__ == "__main__":
    run_eval()