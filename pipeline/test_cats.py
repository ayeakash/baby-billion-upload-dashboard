import os, sys, logging
logging.basicConfig(level=logging.WARNING, format='%(message)s')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_mapper import get_category_fields

tests = [
    ('3-6', 'CVC Words',         'English',  'CVC Words'),
    ('3-6', 'Sight  words',      'English',  'Sight words'),
    ('3-6', 'Simple sentences',  'English',  'Simple sentences'),
    ('3-6', 'English speaking',  'English',  'English Speaking'),
    ('3-6', 'ABC',               'English',  'ABC'),
    ('3-6', 'Colors',            '',         'Colors'),
    ('3-6', 'Fruits',            '',         'Fruits'),
    ('3-6', 'Animals',           'Animals',  'Animals'),
    ('3-6', 'Good habits',       '',         'Good Habits'),
    ('3-6', 'My Body',           '',         'My Body'),
    ('3-6', 'Vehicles',          '',         'Vehicles'),
    ('3-6', 'shapes',            'Maths',    'Shapes'),
    ('0-3', 'ABC',               '',         'ABC'),
    ('0-3', 'Colors',            '',         'Colors'),
]

passes = 0
fails  = 0
for age, notion, exp_parent, exp_cat in tests:
    parent, exact = get_category_fields(age, notion)
    ok = parent.strip() == exp_parent.strip() and exact.strip() == exp_cat.strip()
    status = 'PASS' if ok else 'FAIL got parent=%r cat=%r' % (parent, exact)
    if ok: passes += 1
    else:  fails  += 1
    print('%s | age=%-4s | %-25s -> parent=%-12s cat=%s' % (status, age, notion, parent, exact))

print('\n%d passed, %d failed' % (passes, fails))
