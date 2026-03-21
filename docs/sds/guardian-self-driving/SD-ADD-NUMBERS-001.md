---
title: "Add Two Numbers — Implementation SD"
description: "Simple function + tests for guardian self-driving lifecycle test"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: sd
---

# SD: Add Two Numbers

## Task
Create `state/add_numbers.py` with function `add(a, b)` and `state/test_add_numbers.py` with pytest tests.

## Implementation
```python
# state/add_numbers.py
def add(a, b):
    return a + b
```

```python
# state/test_add_numbers.py
from add_numbers import add

def test_add_integers():
    assert add(2, 3) == 5

def test_add_floats():
    assert add(1.5, 2.5) == 4.0

def test_add_negatives():
    assert add(-1, -2) == -3

def test_add_zero():
    assert add(0, 0) == 0
```

## Acceptance Criteria
- Both files exist in `state/`
- `pytest state/test_add_numbers.py -v` passes all tests
