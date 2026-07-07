import os, sys, logging
logging.basicConfig(level=logging.WARNING, format='%(message)s')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_mapper import get_category_fields

tests = [
    # (age, notion_name, expected_parent, expected_playlist_name)
    # 3-6 English
    ('3-6', 'CVC Words',         'English Basics',    'Read Simple Words'),
    ('3-6', 'Sight  words',      'Ready for School',  'Speak It Right'),
    ('3-6', 'Simple sentences',  'English Basics',    'Start With Sentences'),
    ('3-6', 'English speaking',  'English Basics',    'Speak With Confidence'),
    ('3-6', 'ABC',               'English Basics',    'Know Your Alphabets'),
    # 3-6 Misc
    ('3-6', 'Colors',            'Learn & Explore',   'Learn Color Names'),
    ('3-6', 'Fruits',            'Food',              'Name Tasty Fruits'),
    ('3-6', 'Animals',           'Animals',           'Animals'),
    ('3-6', 'Good habits',       'Good Habits',       'Build Good Habits'),
    ('3-6', 'My Body',           'Good Habits',       'Know Body Parts'),
    ('3-6', 'Vehicles',          "Kids' Favorites",   'Spot Cool Vehicles'),
    ('3-6', 'shapes',            'Ready for School',  'Learn Your Shapes'),
    # 0-3
    ('0-3', 'ABC',               'English Basics',    'Learn Your ABC'),
    ('0-3', 'Colors',            "Kids' Favorites",   'Learn Color Names'),
    ('0-3', 'Musical Instruments', 'Rhymes & Music',  'Listen And Enjoy'),
    ('0-3', 'My Family',         'Me & My Family',    'Meet Your Family'),
    ('0-3', 'Good Habits',       "Kids' Favorites",   'Practice Good Habits'),
    # 6+
    ('6+', 'Nature',             'Geography',         'Explore Nature Around'),
    ('6+', 'Science',            'Science',           'Discover Science Secrets'),
    ('6+', 'Animals',            'Animals',           'Meet Amazing Animals'),
    ('6+', 'Good Habits',        'Good Habits',       'Build Good Habits'),
    ('6+', 'Knowledge',          'Space Adventures',  'Amazing Facts Inside'),
]

passes = 0
fails  = 0
for age, notion, exp_parent, exp_cat in tests:
    parent, exact = get_category_fields(age, notion)
    ok = parent.strip() == exp_parent.strip() and exact.strip() == exp_cat.strip()
    status = 'PASS' if ok else 'FAIL got parent=%r cat=%r' % (parent, exact)
    if ok: passes += 1
    else:  fails  += 1
    print('%s | age=%-4s | %-25s -> parent=%-20s cat=%s' % (status, age, notion, parent, exact))

print('\n%d passed, %d failed' % (passes, fails))
