# Python Tutorial 3-9 Diagnostic Map

Use this map for Python-wide baseline diagnostics. It is intentionally limited to official Python Tutorial chapters 3-9.

## Question Count

Default to 35 questions:

- Chapter 3: 5 questions
- Chapter 4: 5 questions
- Chapter 5: 5 questions
- Chapter 6: 5 questions
- Chapter 7: 5 questions
- Chapter 8: 5 questions
- Chapter 9: 5 questions

This count gives one signal for every core node while staying short enough for a single diagnostic sitting.

## Chapter Nodes

### Chapter 3: An Informal Introduction to Python

- `python.ch3.numbers`: numeric operators, division, floor division, remainder, powers
- `python.ch3.text`: string literals, escaping, raw strings, concatenation, repetition, indexing, slicing, `len()`
- `python.ch3.sequence_indexing`: zero-based indexing, half-open slicing, negative indices, immutability
- `python.ch3.lists`: list literals, indexing, slicing, `append()`, nesting, mutability
- `python.ch3.assignment_mutability`: variable binding, list aliasing, mutation versus rebinding

### Chapter 4: More Control Flow Tools

- `python.ch4.if`: branch selection with `if`/`elif`/`else`
- `python.ch4.for_range`: `for`, `range(start, stop, step)`, loop variable behavior
- `python.ch4.loop_control`: `break`, `continue`, loop `else`, `pass`, `match`
- `python.ch4.functions`: function definition, return values, local variables, docstrings, annotations
- `python.ch4.arguments`: default arguments, keyword arguments, special parameters, `*args`, unpacking, lambda

### Chapter 5: Data Structures

- `python.ch5.list_methods`: list methods, stacks, queues, mutating versus returning values
- `python.ch5.comprehensions`: list comprehensions and nested comprehensions
- `python.ch5.tuples_sequences`: tuples, packing/unpacking, sequence comparisons, `del`
- `python.ch5.sets_dicts`: set operations, dictionaries, membership, keys and values
- `python.ch5.looping_conditions`: `enumerate`, `zip`, sorted/reversed iteration, boolean conditions

### Chapter 6: Modules

- `python.ch6.imports`: modules, import forms, namespaces, attribute access
- `python.ch6.module_execution`: executing modules as scripts and `__name__ == "__main__"`
- `python.ch6.search_path`: `sys.path`, current directory, `PYTHONPATH`, installation defaults
- `python.ch6.dir`: `dir()` and imported names
- `python.ch6.packages`: packages, submodules, `__init__.py`, relative imports

### Chapter 7: Input and Output

- `python.ch7.fstrings_format`: f-strings, `str.format()`, format specifiers, alignment
- `python.ch7.str_repr`: `str()`, `repr()`, display versus representation
- `python.ch7.open_modes`: `open()`, text/binary modes, encoding
- `python.ch7.with_files`: context managers, file methods, iteration, `tell()`, `seek()`
- `python.ch7.json`: `json.dumps`, `json.dump`, `json.loads`, `json.load`

### Chapter 8: Errors and Exceptions

- `python.ch8.syntax_vs_exception`: syntax errors versus runtime exceptions
- `python.ch8.try_except`: `try`/`except`/`else` flow, matching exception classes
- `python.ch8.raise`: `raise`, re-raise, exception chaining
- `python.ch8.finally_cleanup`: `finally` and predefined cleanup actions
- `python.ch8.custom_exceptions`: user-defined exceptions and exception hierarchy

### Chapter 9: Classes

- `python.ch9.namespaces_scopes`: namespaces, scopes, local/global/nonlocal lookup
- `python.ch9.class_definition`: class definition syntax, class objects, instance objects
- `python.ch9.instance_methods`: `self`, method binding, instance attribute assignment
- `python.ch9.class_instance_variables`: class variables versus instance variables
- `python.ch9.inheritance`: inheritance, method override, multiple inheritance basics

## Quality Checks

- Every question must target one primary node and at most one related secondary node.
- Every chapter must include at least one trace/output question and one explanation/transfer question.
- Avoid pure memorization when a small code example can test the same idea.
- Do not require external libraries or topics outside chapters 3-9.
- The overall result should be chapter-level and node-level, not just a single score.
