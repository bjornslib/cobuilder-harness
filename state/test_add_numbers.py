from add_numbers import add

def test_add_integers():
    assert add(2, 3) == 5

def test_add_floats():
    assert add(1.5, 2.5) == 4.0

def test_add_negatives():
    assert add(-1, -2) == -3

def test_add_zero():
    assert add(0, 0) == 0