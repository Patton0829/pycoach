# Python Iterator Chapter Reference

Use this reference when generating questions for the Python iterator chapter and no richer book/chapter source is provided.

## Core Principles

- A Python list, tuple, string, and many containers are iterable objects.
- `iter(obj)` returns an iterator for an iterable object.
- An iterator is stateful; it remembers how far it has been consumed.
- `next(iterator)` returns the next element and advances the iterator state.
- Calling `iter()` on the original iterable again usually creates a fresh iterator.
- Calling `iter()` on an iterator usually returns the same iterator object.
- An exhausted iterator does not restart automatically.
- `next()` on an exhausted iterator raises `StopIteration`.
- A `for` loop internally uses the iterator protocol.
- A generator is an iterator source, but generator details should stay light for beginner iterator chapters.

## Knowledge Nodes

- `python.iterable`: distinguish iterable objects from unrelated values.
- `python.iterator`: explain an iterator as a stateful object.
- `python.iterator.iter`: use `iter()` to create or return an iterator.
- `python.iterator.next`: use `next()` to obtain one element.
- `python.iterator.state`: trace consumption state.
- `python.iterator.exhaustion`: recognize exhausted iterator behavior.
- `python.stop_iteration`: identify the exception after exhaustion.
- `python.for_loop.protocol`: connect `for` loops to `iter()` and `next()`.
- `python.generator.intro`: recognize generators as iterator-related.

## Common Error Types

- `iterable_vs_iterator`: treats an iterable and iterator as identical.
- `iterator_object_vs_element`: confuses iterator object with yielded element.
- `iter_vs_next`: uses `iter()` when `next()` is required or vice versa.
- `iter_advances_state`: believes `iter()` consumes an element.
- `next_argument_error`: passes a non-iterator to `next()`.
- `iterator_exhaustion`: assumes an exhausted iterator restarts automatically.
- `stop_iteration_unrecognized`: does not connect exhaustion with `StopIteration`.
- `for_loop_protocol_confusion`: does not relate `for` loops to the iterator protocol.
- `generator_vs_iterator`: misstates the relationship between generators and iterators.

## Canonical Code Patterns

```python
values = [1, 2]
it = iter(values)
print(next(it))
print(next(it))
```

```python
data = [10, 20]
it = iter(data)
first = next(it)
new_it = iter(data)
second = next(new_it)
```

```python
nums = [1, 2]
it = iter(nums)
print(next(it))
print(next(it))
print(next(it))  # StopIteration
```

```python
for item in [1, 2, 3]:
    print(item)
```

## Question Progression

1. Identify iterable vs iterator.
2. Create an iterator with `iter()`.
3. Retrieve one element with `next()`.
4. Trace state across repeated `next()` calls.
5. Compare `iter(data)` with `next(it)`.
6. Predict output until exhaustion.
7. Name or handle `StopIteration`.
8. Explain the for-loop protocol.
9. Lightly connect generators to iterators.
10. Synthesize the chapter in a short explanation or transfer question.
