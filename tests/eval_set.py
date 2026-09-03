from core.text_to_sql import ask_question
from tests.check_ground_truth import get_ground_truth
import ast
import time


GROUND_TRUTH = None


def matches_ground_truth(result, key):
    if result is None:
        return False
    try:
        actual_values = {str(value) for row in ast.literal_eval(result) for value in row}
    except (SyntaxError, ValueError, TypeError):
        return False

    expected_values = {str(value) for row in GROUND_TRUTH[key] for value in row}
    return actual_values == expected_values


EVAL_CASES = [
    {
        "question": "How many customers are there?",
        "check": lambda r: matches_ground_truth(r, "customer_count"),
    },
    {
        "question": "How many products are there?",
        "check": lambda r: matches_ground_truth(r, "product_count"),
    },
    {
        "question": "How many total orders are there?",
        "check": lambda r: matches_ground_truth(r, "order_count"),
    },
    {
        "question": "Which customers have never placed an order?",
        "check": lambda r: matches_ground_truth(r, "customers_never_ordered"),
    },
    {
        "question": "Which products have never been ordered?",
        "check": lambda r: matches_ground_truth(r, "products_never_ordered"),
    },
    {
        "question": "What is the best-selling product category by total revenue?",
        "check": lambda r: matches_ground_truth(r, "best_selling_category"),
    },
    {
        "question": "What percentage of orders were cancelled?",
        "check": lambda r: matches_ground_truth(r, "cancelled_order_percentage"),
    },
    {
        "question": "Which customer has placed the most orders?",
        "check": lambda r: matches_ground_truth(r, "top_ordering_customers"),
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
        "check": lambda r: matches_ground_truth(r, "customers_above_average_spend"),
    },
    {
        "question": "How many customers have ordered from more than 3 different categories?",
        "check": lambda r: matches_ground_truth(r, "customers_with_more_than_three_categories"),
    },
    {
        "question": "What percentage of total revenue comes from the top 10 customers?",
        "check": lambda r: matches_ground_truth(r, "top_ten_customer_revenue_percentage"),
    },
    {
        "question": "How many distinct months have at least one order?",
        "check": lambda r: matches_ground_truth(r, "months_with_orders"),
    },
    {
        "question": "Which customers have never ordered anything from Electronics?",
        "check": lambda r: matches_ground_truth(r, "customers_never_ordered_electronics"),
    },
    {
        "question": "Kaunse customers ne kabhi Electronics category ka product order nahi kiya?",
        "check": lambda r: matches_ground_truth(r, "customers_never_ordered_electronics"),
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
    global GROUND_TRUTH
    GROUND_TRUTH = get_ground_truth()
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
