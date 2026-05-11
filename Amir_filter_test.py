import ujson

# אלו האינדקסים שאנחנו רוצים לבדוק (ה-CQ עם ה-DISTINCT שנתקעו בלולאה)
target_indices = {16, 17, 18}

input_file = 'benchmarks/literature/literature-rewrite.jsonlines'
output_file = 'benchmarks/literature/test-cq.jsonlines'

with open(input_file, 'r', encoding='utf-8') as f_in, \
     open(output_file, 'w', encoding='utf-8') as f_out:
    for line in f_in:
        obj = ujson.loads(line)
        if obj['index'] in target_indices:
            f_out.write(line)

print(f"Created {output_file} successfully with indices: {target_indices}")