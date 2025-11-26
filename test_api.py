#!/usr/bin/env python3
"""
Integration test script for the LLM Analysis Quiz Solver.
Tests all major scenarios: valid payload, invalid secret, invalid JSON, etc.

Usage:
    python test_api.py [--url http://127.0.0.1:8000]
"""

import sys
import json
import argparse
import httpx
from typing import Optional

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_test(name: str):
    print(f"\n{BOLD}{CYAN}[TEST]{RESET} {name}")

def print_pass(msg: str):
    print(f"{GREEN}✓ PASS{RESET}: {msg}")

def print_fail(msg: str):
    print(f"{RED}✗ FAIL{RESET}: {msg}")

def print_info(msg: str):
    print(f"{YELLOW}ℹ INFO{RESET}: {msg}")

def test_health_check(base_url: str) -> bool:
    """Test server is running and responding."""
    print_test("Server Health Check")
    try:
        response = httpx.get(f"{base_url}/docs", timeout=5)
        if response.status_code == 200:
            print_pass(f"Server responding on {base_url}")
            return True
        else:
            print_fail(f"Server returned {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Cannot connect to server: {e}")
        return False

def test_valid_payload(base_url: str, secret: str, url: str = "https://httpbin.org/html") -> bool:
    """Test valid payload returns 200."""
    print_test("Valid Payload (expect 200 OK)")
    payload = {
        "email": "test@example.com",
        "secret": secret,
        "url": url
    }
    try:
        response = httpx.post(
            f"{base_url}/quiz",
            json=payload,
            timeout=120,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "ok":
                print_pass(f"Got 200 OK with status='ok'")
                if "solver_result" in data:
                    result = data["solver_result"]
                    print_info(f"  Steps: {len(result.get('steps', []))}")
                    print_info(f"  Time: {result.get('total_time_secs', 'N/A')}s")
                    print_info(f"  Within limit: {result.get('within_time_limit', 'N/A')}")
                return True
            else:
                print_fail(f"Got 200 but status='{data.get('status')}'")
                return False
        else:
            print_fail(f"Expected 200, got {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False

def test_invalid_secret(base_url: str) -> bool:
    """Test invalid secret returns 403."""
    print_test("Invalid Secret (expect 403 Forbidden)")
    payload = {
        "email": "test@example.com",
        "secret": "wrong-secret-should-fail",
        "url": "https://httpbin.org/html"
    }
    try:
        response = httpx.post(
            f"{base_url}/quiz",
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 403:
            print_pass(f"Got expected 403 Forbidden")
            return True
        else:
            print_fail(f"Expected 403, got {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False

def test_invalid_json(base_url: str) -> bool:
    """Test invalid JSON returns 400."""
    print_test("Invalid JSON (expect 400 Bad Request)")
    try:
        response = httpx.post(
            f"{base_url}/quiz",
            content="not-valid-json",
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 400:
            print_pass(f"Got expected 400 Bad Request")
            return True
        else:
            print_fail(f"Expected 400, got {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False

def test_missing_fields(base_url: str, secret: str) -> bool:
    """Test missing required fields returns 400."""
    print_test("Missing Fields (expect 400 Bad Request)")
    
    # Test missing 'url'
    payload = {
        "email": "test@example.com",
        "secret": secret,
        # 'url' is missing
    }
    try:
        response = httpx.post(
            f"{base_url}/quiz",
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 400:
            print_pass(f"Got expected 400 for missing 'url' field")
            return True
        else:
            print_fail(f"Expected 400, got {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False

def test_non_string_fields(base_url: str, secret: str) -> bool:
    """Test non-string fields returns 400."""
    print_test("Non-String Fields (expect 400 Bad Request)")
    
    # email as int instead of string
    payload = {
        "email": 12345,
        "secret": secret,
        "url": "https://httpbin.org/html"
    }
    try:
        response = httpx.post(
            f"{base_url}/quiz",
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 400:
            print_pass(f"Got expected 400 for non-string email field")
            return True
        else:
            print_fail(f"Expected 400, got {response.status_code}")
            return False
    except Exception as e:
        print_fail(f"Request failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test LLM Analysis Quiz Solver API")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base API URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--secret", default="eVUyyKnAP956QwwgmWcBfBbD6cSMNW2zsvD8CnO4uYM=", help="Valid secret for testing")
    parser.add_argument("--demo", action="store_true", help="Test against demo endpoint")
    
    args = parser.parse_args()
    base_url = args.url.rstrip('/')
    secret = args.secret
    
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}{YELLOW}  LLM Analysis Quiz Solver - API Test Suite{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"  Base URL: {base_url}")
    print(f"  Secret: {secret[:20]}...")
    if args.demo:
        print(f"  Mode: Demo Endpoint Test")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")
    
    # Run tests
    results = []
    
    # Health check first
    if not test_health_check(base_url):
        print(f"\n{RED}Server not responding. Aborting tests.{RESET}")
        return 1
    
    # Run all tests
    results.append(("Valid Payload", test_valid_payload(base_url, secret)))
    results.append(("Invalid Secret", test_invalid_secret(base_url)))
    results.append(("Invalid JSON", test_invalid_json(base_url)))
    results.append(("Missing Fields", test_missing_fields(base_url, secret)))
    results.append(("Non-String Fields", test_non_string_fields(base_url, secret)))
    
    # Demo endpoint test (optional)
    if args.demo:
        print_test("Demo Endpoint Test")
        demo_passed = test_valid_payload(
            base_url,
            secret,
            url="https://tds-llm-analysis.s-anand.net/demo"
        )
        results.append(("Demo Endpoint", demo_passed))
    
    # Summary
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}Test Summary{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{GREEN}✓ PASS{RESET}" if result else f"{RED}✗ FAIL{RESET}"
        print(f"{status}: {test_name}")
    
    print(f"\n{BOLD}{CYAN}Total: {passed}/{total} tests passed{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}\n")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
