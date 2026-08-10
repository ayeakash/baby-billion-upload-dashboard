"""
List all successfully uploaded thumbnails
"""

# All successfully uploaded items from both upload attempts
UPLOADED = {
    'playlists': [
        'ABC Learning',
        'Animals',
        'Around Us',
        'Curious Kids',
        'English Basics',
        'Geography',
        'Hindi Basics',
        'Talk & Manners',
        'Maths',
        'Nature',
        'Numbers & Easy Math',
        'Our World',
        'Rhymes & Music',
        'Science',
        'Stories'
    ],
    'characters': [
        'Arjun',
        'Golu',
        'Guddi',
        'Hanuman',
        'Krishna',
        'Mia',
        'Mishka',
        'Priya',
        'Shivji',
        'Sindbad',
        'Tara',
        'Teja',
        'Tenali',
        'Veer',
        'Zoya'
    ],
    'categories': [
        'Learn Your ABC',
        'About India',
        'Try These Actions',
        'Aladdin',
        'Clothes',
        'Learn Color names',
        'What Do They Do',
        'Visit New Countries',
        'Understand Your Feelings',
        'Learn New Words',
        'Meet Farm Animals',
        'Celebrate With Everyone',
        'Choose Healthy Foods',
        'Fractions',
        'Name Your Fruits',
        'Practice Good Habits',
        'Greater & Lesser',
        'Know Body Parts',
        'Find Things Around',
        'Knowledge',
        'Mishka And Momo',
        'Shapes With Ms Isha',
        'Pronounce With Ms Nidhi',
        'Maths With Ms Pranika',
        'Meet Your Family',
        'Learn Opposite Words',
        'Panchatantra',
        'Let\'s Go Outside',
        'Watch Plants Grow',
        'Prepositions',
        'Safety',
        'Read Simple Words',
        'Start With Sentences',
        'Visit Outer Space',
        'Explore Different Sports',
        'Time',
        'Find Favorite Toys',
        'Varnmala',
        'Name Your Veggies',
        'Spot Moving Vehicles'
    ]
}

print("\n" + "="*80)
print("ALL SUCCESSFULLY UPLOADED THUMBNAILS")
print("="*80 + "\n")

print("PLAYLISTS (15):")
print("-"*80)
for idx, item in enumerate(sorted(UPLOADED['playlists']), 1):
    print(f"{idx:2d}. {item}")

print("\n\nCHARACTERS (15):")
print("-"*80)
for idx, item in enumerate(sorted(UPLOADED['characters']), 1):
    print(f"{idx:2d}. {item}")

print("\n\nCATEGORIES (40):")
print("-"*80)
for idx, item in enumerate(sorted(UPLOADED['categories']), 1):
    print(f"{idx:2d}. {item}")

print("\n" + "="*80)
total = len(UPLOADED['playlists']) + len(UPLOADED['characters']) + len(UPLOADED['categories'])
print(f"TOTAL UPLOADED: {total} items")
print(f"  • Playlists:  {len(UPLOADED['playlists'])}")
print(f"  • Characters: {len(UPLOADED['characters'])}")
print(f"  • Categories: {len(UPLOADED['categories'])}")
print("="*80 + "\n")
