import pathlib
test_code = open(r'E:\codex\cdx-brain\tests\_extractor_source.py', 'r', encoding='utf-8').read()
with open(r'E:\codex\cdx-brain\tests\test_extractor.py', 'w', encoding='utf-8') as f:
    f.write(test_code)
print('OK')
