# Python Basics (sample teaching text, original)

## Loops

A loop repeats a block of code. A `for` loop walks over the items of a sequence, one at a time.

```python
for n in [3, 5, 8]:
    print(n)
```

The loop variable takes each value in turn. After the last item the loop ends by itself.

### Counting with range

`range(stop)` produces the numbers 0 up to, but not including, `stop`. So `range(3)` gives 0, 1, 2.
A common mistake is to go one step too far, which is called an off-by-one error.
Indexes of a list with n items run from 0 to n - 1.

## Accumulators

An accumulator is a variable that collects a result while a loop runs, such as a running total.
It must be given a starting value before the loop. For a sum, the starting value is 0.

```python
total = 0
for n in [3, 5, 8]:
    total = total + n
```

## Common errors

### Debugging an off-by-one error

Trace the loop by hand with a tiny list. Write down the loop variable on every pass,
especially the first and the last. Compare the last value with the largest valid index.

## Exercises

1. Write a loop that prints each item of a list.
2. Compute the average of a list of numbers.

## Recursion

A recursive function calls itself on a smaller input. It needs a base case: an input for which
it returns an answer without calling itself. Without a base case the calls never stop.
