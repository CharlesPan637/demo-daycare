#!/usr/bin/env python3
"""Add Portfolio_Moments (Table14) and Monthly_Books (Table15) to Grist."""
import os, sys, json
import requests

API_KEY = os.getenv("GRIST_API_KEY")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://127.0.0.1:8096")
DOC_ID = os.getenv("GRIST_DOC_ID", "new~77esxLe65dVuwRr3hSXA52~5")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def api(method, path, data=None):
    url = f"{BASE_URL}/api/docs/{DOC_ID}{path}"
    kwargs = {"headers": HEADERS}
    if data is not None:
        kwargs["json"] = data
    r = requests.request(method, url, **kwargs)
    if r.status_code >= 400:
        print(f"  ERROR {method} {path}: {r.status_code} {r.text[:300]}")
        return None
    return r.json() if r.text else None

# ═══════════════════════════════════════════════════════════
# TABLE 14: Portfolio_Moments
# ═══════════════════════════════════════════════════════════
print("Creating Portfolio_Moments table...")
portfolio_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "date", "type": "Text"},
    {"id": "moment_type", "type": "Text"},        # Photo, Video, Audio, Drawing
    {"id": "title", "type": "Text"},
    {"id": "description", "type": "Text"},
    {"id": "category", "type": "Text"},            # Physical, Cognitive, Language, Social-Emotional, Creative
    {"id": "media_url", "type": "Text"},           # Minio path
    {"id": "media_type", "type": "Text"},          # image/jpeg, video/mp4, audio/ogg
    {"id": "tags", "type": "Text"},
    {"id": "staff", "type": "Ref:Staff"},
    {"id": "is_highlight", "type": "Bool"},        # Featured in monthly book
]
result = api("POST", "/tables", {"tables": [{"columns": portfolio_cols, "tableName": "Portfolio_Moments"}]})
if not result:
    print("ERROR: Failed to create Portfolio_Moments table")
    sys.exit(1)
portfolio_id = result["tables"][0]["id"]
print(f"  Created: {portfolio_id}")

# ═══════════════════════════════════════════════════════════
# TABLE 15: Monthly_Books
# ═══════════════════════════════════════════════════════════
print("Creating Monthly_Books table...")
book_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "month", "type": "Text"},               # "2026-05"
    {"id": "title", "type": "Text"},
    {"id": "cover_description", "type": "Text"},
    {"id": "highlights", "type": "Text"},           # Summary paragraphs
    {"id": "moment_ids", "type": "Text"},           # Comma-separated Portfolio_Moments refs
    {"id": "teacher_note", "type": "Text"},
    {"id": "status", "type": "Text"},               # Draft, Published, Sent
    {"id": "staff", "type": "Ref:Staff"},
]
result = api("POST", "/tables", {"tables": [{"columns": book_cols, "tableName": "Monthly_Books"}]})
if not result:
    print("ERROR: Failed to create Monthly_Books table")
    sys.exit(1)
book_id = result["tables"][0]["id"]
print(f"  Created: {book_id}")

# ═══════════════════════════════════════════════════════════
# SEED PORTFOLIO MOMENTS
# ═══════════════════════════════════════════════════════════
print("\nSeeding portfolio moments...")

moments = [
    # ── Emma (child 1, age 3) ──
    {"child": 1, "date": "2026-05-15", "moment_type": "Photo",
     "title": "Purple Dinosaur Finger Painting",
     "description": "Emma created her first representational painting — 'It's a purple dinosaur!' She used three colors and described her work to Ms. Rachel with excitement. This is a significant leap from abstract scribbling to intentional representation.",
     "category": "Creative", "media_url": "minio://daycare-portfolio/emma/purple-dinosaur-20260515.jpg",
     "media_type": "image/jpeg", "tags": "Art, Painting, First Representational, Language, Descriptive",
     "staff": 2, "is_highlight": True},
    {"child": 1, "date": "2026-05-20", "moment_type": "Photo",
     "title": "Twelve-Block Tower",
     "description": "Emma built a tower of 12 blocks, carefully counting each one as she stacked. The tower stood for over a minute before she knocked it down with a delighted giggle. Demonstrates fine motor control and 1:1 correspondence counting.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/emma/block-tower-20260520.jpg",
     "media_type": "image/jpeg", "tags": "Fine Motor, Counting, Math, Persistence",
     "staff": 1, "is_highlight": True},
    {"child": 1, "date": "2026-04-10", "moment_type": "Audio",
     "title": "First Full ABC Song",
     "description": "During morning circle, Emma sang the entire alphabet song from A to Z without prompting. Clear pronunciation through LMNOP (the tricky part!). Her confidence is growing — she used to only mouth the words quietly.",
     "category": "Language", "media_url": "minio://daycare-portfolio/emma/abc-song-20260410.ogg",
     "media_type": "audio/ogg", "tags": "Language, Alphabet, Singing, Confidence, Circle Time",
     "staff": 1, "is_highlight": False},
    {"child": 1, "date": "2026-03-05", "moment_type": "Drawing",
     "title": "First Self-Portrait",
     "description": "Emma drew her first self-portrait with crayons — a round head, two eyes, a smile, and 'purple hair like Mommy's.' She added arms coming directly from the head (developmentally appropriate for age 3). This is a milestone for self-awareness and fine motor skills.",
     "category": "Creative", "media_url": "minio://daycare-portfolio/emma/self-portrait-20260305.png",
     "media_type": "image/png", "tags": "Drawing, Self-Awareness, Fine Motor, First Portrait",
     "staff": 2, "is_highlight": True},

    # ── Liam (child 2, age 4) ──
    {"child": 2, "date": "2026-05-25", "moment_type": "Audio",
     "title": "First Independent Count to 100",
     "description": "During free play, Liam sat at the number chart and counted aloud from 1 to 100 without any assistance. He paused briefly at 69→70 and 79→80 but self-corrected. This is advanced for a 4-year-old and shows strong number sense.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/liam/count-to-100-20260525.ogg",
     "media_type": "audio/ogg", "tags": "Math, Counting, Advanced, Independence, Number Sense",
     "staff": 1, "is_highlight": True},
    {"child": 2, "date": "2026-05-18", "moment_type": "Video",
     "title": "Reading 'Brown Bear' to the Class",
     "description": "Liam volunteered to 'read' Brown Bear, Brown Bear to the preschool group. He held the book facing outward (like a real teacher!), turned pages correctly, and recited the story from memory with expressive voices for each animal. Five classmates sat attentively.",
     "category": "Language", "media_url": "minio://daycare-portfolio/liam/reading-brown-bear-20260518.mp4",
     "media_type": "video/mp4", "tags": "Reading, Memory, Leadership, Expression, Pre-Literacy",
     "staff": 1, "is_highlight": True},
    {"child": 2, "date": "2026-05-27", "moment_type": "Photo",
     "title": "Simon Says Leader",
     "description": "Liam organized a group of 5 peers for Simon Says on the playground. He explained the rules clearly, took turns being 'Simon', and helped younger children understand when to follow commands. Natural leadership emerging.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/liam/simon-says-leader-20260527.jpg",
     "media_type": "image/jpeg", "tags": "Leadership, Peer Interaction, Communication, Initiative",
     "staff": 2, "is_highlight": False},
    {"child": 2, "date": "2026-04-05", "moment_type": "Photo",
     "title": "First Science Experiment — Volcano!",
     "description": "During STEM time, Liam led the baking soda and vinegar volcano experiment. He carefully measured the ingredients and gasped when the 'lava' erupted. 'It's chemistry!' he announced. His curiosity drives him to ask 'why' and 'what if' constantly.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/liam/volcano-experiment-20260405.jpg",
     "media_type": "image/jpeg", "tags": "STEM, Science, Curiosity, Measuring, Cause-Effect",
     "staff": 2, "is_highlight": True},

    # ── Sophia (child 3, age 2) ──
    {"child": 3, "date": "2026-02-10", "moment_type": "Video",
     "title": "First Independent Walk to Circle Area",
     "description": "Sophia walked independently from her cubby to the circle area — a 20-foot journey! She carried her stuffed bunny under one arm and smiled when she reached the rug. This was her first full walk across the classroom without holding a teacher's hand.",
     "category": "Physical", "media_url": "minio://daycare-portfolio/sophia/first-walk-classroom-20260210.mp4",
     "media_type": "video/mp4", "tags": "Gross Motor, Walking, Independence, First, Confidence",
     "staff": 1, "is_highlight": True},
    {"child": 3, "date": "2026-01-15", "moment_type": "Audio",
     "title": "First Clear Word — 'Bunny'",
     "description": "During morning drop-off, Sophia clearly said 'bunny' while reaching for her stuffed rabbit. This is her first clearly articulated word observed at daycare. Previously she communicated through gestures and sounds. Her mother confirmed she says it at home too.",
     "category": "Language", "media_url": "minio://daycare-portfolio/sophia/first-word-bunny-20260115.ogg",
     "media_type": "audio/ogg", "tags": "Language, First Word, Communication, Speech, Milestone",
     "staff": 3, "is_highlight": True},
    {"child": 3, "date": "2026-05-26", "moment_type": "Photo",
     "title": "First Observed Sharing — Sharing Bunny",
     "description": "During rest time, another toddler was crying. Sophia walked over, hesitated for a moment, then placed her beloved stuffed bunny in the other child's arms. The crying stopped. Sophia stood watching for a moment, then sat down nearby. First observed empathic sharing — a major social-emotional milestone for age 2.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/sophia/sharing-bunny-20260526.jpg",
     "media_type": "image/jpeg", "tags": "Sharing, Empathy, Social, Milestone, First, Kindness",
     "staff": 1, "is_highlight": True},
    {"child": 3, "date": "2026-03-20", "moment_type": "Drawing",
     "title": "First Finger Painting — Blue and Yellow",
     "description": "Sophia's first experience with finger paint. She initially touched the paint with one fingertip and looked at her hand in surprise. Within minutes she was swirling blue and yellow together, creating green by accident. This sensory exploration is essential for creative development at age 2.",
     "category": "Creative", "media_url": "minio://daycare-portfolio/sophia/first-finger-paint-20260320.png",
     "media_type": "image/png", "tags": "Art, Sensory, First Painting, Color Mixing, Fine Motor",
     "staff": 2, "is_highlight": True},

    # ── Noah (child 4, age 3) ──
    {"child": 4, "date": "2026-05-27", "moment_type": "Photo",
     "title": "48-Piece Puzzle Completed Independently",
     "description": "Noah selected a 48-piece dinosaur puzzle from the puzzle station and completed it entirely on his own in 12 minutes. He used edge-piece strategy and color matching — sophisticated problem-solving for age 3. When finished, he quietly admired his work for a full minute before putting it away.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/noah/48-piece-puzzle-20260527.jpg",
     "media_type": "image/jpeg", "tags": "Problem Solving, Puzzles, Persistence, Fine Motor, Strategy, Advanced",
     "staff": 2, "is_highlight": True},
    {"child": 4, "date": "2026-04-15", "moment_type": "Video",
     "title": "Puzzle Time-Lapse — 24-Piece Challenge",
     "description": "Time-lapse captures Noah methodically solving a 24-piece puzzle. He sorts by color first, then edge pieces, then fills in the middle. Total solve time: 7 minutes. His concentration is remarkable — he doesn't look up once.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/noah/puzzle-timelapse-20260415.mp4",
     "media_type": "video/mp4", "tags": "Puzzles, Focus, Strategy, Problem Solving, Persistence",
     "staff": 2, "is_highlight": False},
    {"child": 4, "date": "2026-03-10", "moment_type": "Audio",
     "title": "First Count to 50",
     "description": "During morning circle counting, Noah volunteered to count aloud and reached 50 for the first time. He paused at 29→30 (the decade transition) but continued confidently. His number recognition now extends to 100 on the wall chart.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/noah/count-to-50-20260310.ogg",
     "media_type": "audio/ogg", "tags": "Counting, Math, Number Sense, Circle Time, Confidence",
     "staff": 1, "is_highlight": False},

    # ── Ava (child 5, age 4) ──
    {"child": 5, "date": "2026-05-26", "moment_type": "Video",
     "title": "First Book Read Aloud to Peers",
     "description": "Ava read 'Brown Bear, Brown Bear, What Do You See?' aloud to a small group of 3 classmates during free play. She held the book correctly, turned pages one at a time, and used different voices for each animal. Three children gathered around to listen, completely engaged.",
     "category": "Language", "media_url": "minio://daycare-portfolio/ava/reading-brown-bear-20260526.mp4",
     "media_type": "video/mp4", "tags": "Reading, Leadership, Expression, Pre-Literacy, Confidence",
     "staff": 1, "is_highlight": True},
    {"child": 5, "date": "2026-04-20", "moment_type": "Audio",
     "title": "Original Story — 'The Princess and the Rainbow Unicorn'",
     "description": "Ava created and dictated an original story during writing center: 'Once upon a time, a princess found a rainbow unicorn. They flew to a castle made of candy and had a tea party with a dragon who was actually nice.' Demonstrates narrative structure, imagination, and sequencing.",
     "category": "Language", "media_url": "minio://daycare-portfolio/ava/original-story-20260420.ogg",
     "media_type": "audio/ogg", "tags": "Storytelling, Imagination, Narrative, Language, Creative Writing",
     "staff": 1, "is_highlight": True},
    {"child": 5, "date": "2026-02-05", "moment_type": "Drawing",
     "title": "First Independently Written Name",
     "description": "Ava wrote her name 'AVA' independently for the first time at the writing center. All three letters are recognizable, written in capital letters with the A's having crossbars. She was so proud she called Ms. Rachel over to see. This marks readiness for more structured pre-writing activities.",
     "category": "Language", "media_url": "minio://daycare-portfolio/ava/first-written-name-20260205.png",
     "media_type": "image/png", "tags": "Writing, Name Recognition, Pre-Literacy, Fine Motor, First, Pride",
     "staff": 1, "is_highlight": True},
    {"child": 5, "date": "2026-05-10", "moment_type": "Photo",
     "title": "Garden Project — First Sprout!",
     "description": "Ava's bean seed (planted May 1) sprouted! She has been watering it daily and checking for growth each morning. When she saw the green shoot, she ran to get Mr. Carlos: 'It's alive! My seed is alive!' This science observation project teaches responsibility and natural cycles.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/ava/bean-sprout-20260510.jpg",
     "media_type": "image/jpeg", "tags": "Science, Nature, Responsibility, Observation, STEM, Gardening",
     "staff": 2, "is_highlight": False},

    # ── Oliver (child 6, age 2) ──
    {"child": 6, "date": "2026-03-01", "moment_type": "Photo",
     "title": "First Day in Toddlers Room",
     "description": "Oliver transitioned from the Infant room to the Toddler room today. He walked in holding Ms. Jessica's hand, explored each station curiously, and sat at the toddler table for snack like a 'big kid.' No tears — just wonder. A smooth transition that speaks to his adaptability.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/oliver/transition-toddlers-20260301.jpg",
     "media_type": "image/jpeg", "tags": "Transition, Independence, Adaptability, First Day, Social",
     "staff": 3, "is_highlight": True},
    {"child": 6, "date": "2026-05-27", "moment_type": "Video",
     "title": "First Empathy — Comforting a Crying Friend",
     "description": "When another toddler started crying during free play, Oliver stopped what he was doing, walked over, and offered his toy car. When the crying didn't stop, he sat down next to the child and patted their arm. He stayed until the child calmed down. This is Oliver's first observed empathic response — remarkable for a 2-year-old.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/oliver/empathy-moment-20260527.mp4",
     "media_type": "video/mp4", "tags": "Empathy, Kindness, Social, First, Milestone, Emotional Intelligence",
     "staff": 3, "is_highlight": True},
    {"child": 6, "date": "2026-04-10", "moment_type": "Photo",
     "title": "First Six-Block Tower",
     "description": "Oliver stacked six wooden blocks into a tower — his highest yet! He knocked it down with a delighted squeal and immediately started rebuilding. Block play develops spatial reasoning, fine motor control, and cause-and-effect understanding.",
     "category": "Physical", "media_url": "minio://daycare-portfolio/oliver/six-block-tower-20260410.jpg",
     "media_type": "image/jpeg", "tags": "Fine Motor, Building, Cause-Effect, Spatial Reasoning, Persistence",
     "staff": 2, "is_highlight": False},

    # ── Isabella (child 7, age 3) ──
    {"child": 7, "date": "2026-05-25", "moment_type": "Audio",
     "title": "First Unprompted 3-Word Sentence — 'More Juice Please'",
     "description": "During afternoon snack, Isabella looked at Ms. Jessica and said 'More juice please' — a complete, unprompted 3-word sentence with a polite marker. This is a significant SLP goal achievement. Previously, Isabella communicated primarily through single words and gestures. Her speech therapist was thrilled with the recording.",
     "category": "Language", "media_url": "minio://daycare-portfolio/isabella/three-word-sentence-20260525.ogg",
     "media_type": "audio/ogg", "tags": "Speech, SLP Goal, Language, Communication, First Sentence, Milestone",
     "staff": 3, "is_highlight": True},
    {"child": 7, "date": "2026-04-05", "moment_type": "Video",
     "title": "First Circle Time Participation",
     "description": "Isabella joined morning circle and sang along with the group for the first time. Previously she would sit at the edge and observe. Today she sat in the circle, clapped during the weather song, and even did the hand motions for 'Itsy Bitsy Spider.' A breakthrough for social participation.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/isabella/circle-time-participation-20260405.mp4",
     "media_type": "video/mp4", "tags": "Circle Time, Social Participation, Singing, Confidence, Breakthrough",
     "staff": 1, "is_highlight": True},
    {"child": 7, "date": "2026-03-15", "moment_type": "Photo",
     "title": "First 12-Piece Puzzle — Farm Animals",
     "description": "Isabella completed a 12-piece farm animal puzzle independently during quiet time. She used picture-matching strategy and persisted through frustration when pieces didn't fit. When she placed the last piece (the cow), she smiled and looked up at Ms. Rachel for acknowledgment.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/isabella/first-puzzle-complete-20260315.jpg",
     "media_type": "image/jpeg", "tags": "Puzzles, Problem Solving, Persistence, Fine Motor, First, Pride",
     "staff": 1, "is_highlight": False},

    # ── Ethan (child 8, age 4) ──
    {"child": 8, "date": "2026-05-27", "moment_type": "Video",
     "title": "Simon Says — Organized Game for 5 Peers",
     "description": "Ethan independently organized a game of Simon Says for five classmates on the playground. He explained the rules, demonstrated how to play, took the role of 'Simon' for the first round, and then let other children take turns leading. This shows leadership, communication, and fairness — advanced social skills for age 4.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/ethan/simon-says-organizer-20260527.mp4",
     "media_type": "video/mp4", "tags": "Leadership, Organization, Communication, Fairness, Peer Interaction, Advanced",
     "staff": 2, "is_highlight": True},
    {"child": 8, "date": "2026-05-10", "moment_type": "Photo",
     "title": "Helping a Younger Child — Shoes",
     "description": "Ethan noticed Oliver struggling with his Velcro shoes after nap time. Without being asked, he knelt down and showed Oliver how to line up the straps and press them down. 'You try now,' he encouraged. Oliver succeeded on his second try. Ethan's patience and kindness are remarkable.",
     "category": "Social-Emotional", "media_url": "minio://daycare-portfolio/ethan/helping-oliver-shoes-20260510.jpg",
     "media_type": "image/jpeg", "tags": "Kindness, Mentoring, Patience, Helping, Social, Leadership",
     "staff": 3, "is_highlight": True},
    {"child": 8, "date": "2026-04-25", "moment_type": "Drawing",
     "title": "Journal Entry — 'My Family'",
     "description": "Ethan drew a detailed family portrait in his journal: four figures standing on green grass under a yellow sun. Each figure has a body (not just limbs from head — developmentally advanced), and he labeled each one: 'Me,' 'Mom,' 'Dad,' 'Max' (the dog). He wrote the labels by sounding out each word phonetically.",
     "category": "Creative", "media_url": "minio://daycare-portfolio/ethan/my-family-journal-20260425.png",
     "media_type": "image/png", "tags": "Drawing, Writing, Family, Phonetic Spelling, Self-Expression, Advanced",
     "staff": 1, "is_highlight": True},
    {"child": 8, "date": "2026-05-05", "moment_type": "Photo",
     "title": "STEM Challenge — Bridge Builder",
     "description": "During STEM exploration, Ethan was challenged to build a bridge between two tables using only popsicle sticks and clothespins. After three attempts, his bridge held a small toy car. 'I'm an engineer!' he declared. Demonstrates design thinking, persistence, and creative problem-solving.",
     "category": "Cognitive", "media_url": "minio://daycare-portfolio/ethan/stem-bridge-20260505.jpg",
     "media_type": "image/jpeg", "tags": "STEM, Engineering, Design Thinking, Persistence, Creativity",
     "staff": 2, "is_highlight": True},
]

result = api("POST", f"/tables/{portfolio_id}/records",
             {"records": [{"fields": m} for m in moments]})
print(f"  {len(moments)} portfolio moments added")

# ═══════════════════════════════════════════════════════════
# SEED MONTHLY BOOKS (May 2026)
# ═══════════════════════════════════════════════════════════
print("\nSeeding monthly books (May 2026)...")

# We need the actual portfolio record IDs to reference them.
# Fetch them to get the IDs.
pf_resp = api("GET", f"/tables/{portfolio_id}/records")
pf_records = pf_resp.get("records", []) if pf_resp else []
# Build lookup: (child_id, title) → record_id
pf_lookup = {}
for r in pf_records:
    key = (r["fields"]["child"], r["fields"]["title"])
    pf_lookup[key] = r["id"]

def pf_ids_for_child(child_num, titles):
    """Get portfolio record IDs for a child's specific moment titles."""
    ids = []
    for title in titles:
        rid = pf_lookup.get((child_num, title))
        if rid:
            ids.append(str(rid))
    return ",".join(ids) if ids else ""

books = [
    {"child": 1, "month": "2026-05", "title": "Emma's May Magic — Art, Blocks & Songs",
     "cover_description": "A month of creative explosion! Emma discovered representational art, mastered block-building to 12, and found her singing voice.",
     "highlights": "This month Emma painted her first representational artwork — 'a purple dinosaur' — and used descriptive language to tell us all about it. She built a 12-block tower while counting each block aloud, showing growing number sense. During circle time, she now sings confidently and initiates conversations with peers at the art station. Her shyness at drop-off has noticeably decreased — she waves goodbye and runs to the art table.",
     "teacher_note": "Emma is blossoming this spring. Her language development is accelerating — she's using more descriptive words and initiating conversations. I'm especially proud of how she's using art as a form of self-expression. For June, we'll encourage more peer collaboration during art projects to build on her growing social confidence. — Ms. Rachel",
     "moment_titles": ["Purple Dinosaur Finger Painting", "Twelve-Block Tower"],
     "staff": 1},

    {"child": 2, "month": "2026-05", "title": "Liam's Big Month — 100, Books & Leadership",
     "cover_description": "Counting to 100, reading to classmates, leading playground games — Liam is kindergarten-ready and shining as a classroom leader.",
     "highlights": "Liam achieved two major academic milestones this month: counting independently to 100 and reading 'Brown Bear' aloud to the class with expressive voices. On the playground he organized Simon Says for five peers, demonstrating natural leadership. His curiosity during STEM activities ('It's chemistry!') shows scientific thinking emerging. He continues to be a kind helper to younger children.",
     "teacher_note": "Liam is more than ready for kindergarten academically, but what makes me proudest is his character. He leads with kindness, includes everyone, and his excitement for learning is contagious. His DTaP booster is due soon — I've noted it in his file. For June, we'll focus on journal writing to complement his reading skills. — Ms. Rachel",
     "moment_titles": ["First Independent Count to 100", "Reading 'Brown Bear' to the Class"],
     "staff": 1},

    {"child": 3, "month": "2026-05", "title": "Sophia's May Milestones — Sharing, Walking & Wonder",
     "cover_description": "A tender month: Sophia's first observed act of sharing, growing independence in walking, and discovery of the joy of art.",
     "highlights": "Sophia had a breakthrough social-emotional moment this month — she comforted a crying peer by sharing her beloved stuffed bunny, her first observed empathic act. She now walks confidently across the classroom and navigates the toddler play equipment independently. Her vocabulary is growing weekly with new words like 'more,' 'please,' 'water,' and 'outside.' During art, she delights in finger painting and discovering what happens when colors mix.",
     "teacher_note": "Sophia's sharing moment with her bunny brought tears to my eyes. For a 2-year-old, sharing a comfort object is profound — it shows deep emotional intelligence and empathy. We're supporting her language explosion by narrating activities and giving her time to respond. Her dairy allergy is well-managed; she's great about asking 'has milk?' before eating. — Ms. Rachel",
     "moment_titles": ["First Observed Sharing — Sharing Bunny"],
     "staff": 1},

    {"child": 4, "month": "2026-05", "title": "Noah's Puzzle Power — Focus, Strategy & Pride",
     "cover_description": "Noah conquered a 48-piece puzzle this month — a stunning display of focus, strategy, and the quiet pride of independent achievement.",
     "highlights": "Noah's puzzle abilities have reached a new level: he completed a 48-piece dinosaur puzzle independently in 12 minutes, using sophisticated edge-sorting and color-matching strategies. His concentration is remarkable — he works quietly and methodically. Beyond puzzles, Noah enjoys building intricate structures with Magna-Tiles and has started showing interest in number games during circle time. He's a calming presence in the classroom.",
     "teacher_note": "Noah's puzzle focus is genuinely advanced for age 3 — the 48-piece completion would be impressive for a 5-year-old. He processes information methodically and takes quiet pride in his work. I'd love to see him share his puzzle strategies with peers next month — it would be a great way to build on his strengths while encouraging peer interaction. — Mr. Carlos",
     "moment_titles": ["48-Piece Puzzle Completed Independently"],
     "staff": 2},

    {"child": 5, "month": "2026-05", "title": "Ava's May Story — Reading, Seeds & Imagination",
     "cover_description": "From reading aloud to peers to watching her bean seed sprout, Ava's love of stories — both in books and in nature — flourished this month.",
     "highlights": "Ava took a big step into literacy leadership this month by reading 'Brown Bear' aloud to three classmates, using expressive voices and proper book handling. Her bean sprout project showed dedication — she watered it daily and was overjoyed at the first green shoot. She continues to create elaborate stories during writing center time. Her confidence as an emerging reader is beautiful to watch.",
     "teacher_note": "Ava is an emerging reader in the truest sense — she doesn't just decode words, she brings stories to life. Her bean sprout project showed patience and responsibility. We are working with her parents on getting her overdue DTaP and Polio boosters scheduled — the immunization tracker flagged both. Overall, Ava is thriving and ready for more challenging literacy activities in June. — Ms. Rachel",
     "moment_titles": ["First Book Read Aloud to Peers", "Garden Project — First Sprout!"],
     "staff": 1},

    {"child": 6, "month": "2026-05", "title": "Oliver's Heart — Empathy, Transitions & Towers",
     "cover_description": "Oliver showed us the size of his heart this month — comforting a crying friend, settling into toddler routines, and building ever-taller towers.",
     "highlights": "Oliver's empathy moment — comforting a crying peer without any adult prompting — was the most talked-about moment in the toddler room this month. For a 2-year-old who just transitioned from infants in March, this shows remarkable emotional intelligence. He's now fully settled into toddler routines, participates eagerly in snack time, and has discovered the joy of block-building. His six-block tower was a proud achievement.",
     "teacher_note": "Oliver has one of the biggest hearts I've seen in 15 years of teaching. His instinct to comfort others is rare and precious at age 2. We're nurturing this by modeling kindness language ('Oliver helped his friend feel better'). His transition from the infant room is now complete — he's a happy, engaged toddler. Next month we'll work on self-help skills like putting on his own shoes. — Mr. Carlos",
     "moment_titles": ["First Empathy — Comforting a Crying Friend"],
     "staff": 2},

    {"child": 7, "month": "2026-05", "title": "Isabella's Voice — Sentences, Songs & Confidence",
     "cover_description": "A breakthrough month: Isabella spoke her first unprompted 3-word sentence, sang with the group, and is finding her voice every day.",
     "highlights": "Isabella achieved a major SLP goal this month: she produced an unprompted 3-word sentence ('More juice please') with a polite marker — a first! She is now attempting 2-3 word combinations regularly. Her confidence in group settings has grown dramatically; she sits in the circle, claps during songs, and joins the hand motions. We have recorded her progress to share with her speech therapist. Each day brings new words.",
     "teacher_note": "Isabella's progress this month has been extraordinary. The 'more juice please' moment made every staff member in earshot tear up. Her speech therapist says the consistent language-rich environment at daycare is making a measurable difference. We're continuing to use wait-time after questions, narrate play, and celebrate every communication attempt. Isabella, we are so proud of you. — Ms. Jessica",
     "moment_titles": ["First Unprompted 3-Word Sentence — 'More Juice Please'"],
     "staff": 3},

    {"child": 8, "month": "2026-05", "title": "Ethan the Leader — Games, Kindness & Engineering",
     "cover_description": "Ethan organized playground games, helped younger children, built a bridge that held a toy car, and is emerging as a natural classroom leader.",
     "highlights": "Ethan's leadership qualities shone this month: he independently organized Simon Says for five peers, taught Oliver how to fasten his shoes, and declared 'I'm an engineer!' after building a popsicle-stick bridge that held a toy car. His journal drawings now include phonetic labels — early writing! He balances confidence with kindness, never excluding anyone from his games. Ethan sets the social tone for the Pre-K room.",
     "teacher_note": "Ethan is ready for kindergarten — not just academically, but socially and emotionally. He's the rare child who leads without dominating and helps without being asked. His bridge-building persistence (three attempts!) showed grit. For June, we'll introduce more complex STEM challenges and encourage him to mentor younger children during buddy reading time. He has a gift for teaching others. — Mr. Carlos",
     "moment_titles": ["Simon Says — Organized Game for 5 Peers", "STEM Challenge — Bridge Builder", "Helping a Younger Child — Shoes"],
     "staff": 2},
]

book_records = []
for b in books:
    moment_ids = pf_ids_for_child(b["child"], b.pop("moment_titles"))
    b["moment_ids"] = moment_ids
    b["status"] = "Published"
    book_records.append({"fields": b})

result = api("POST", f"/tables/{book_id}/records", {"records": book_records})
print(f"  {len(books)} monthly books added (May 2026)")

# Summary
print(f"\n{'='*60}")
print(f"Portfolio_Moments: {portfolio_id} — {len(moments)} moments across 8 children")
print(f"Monthly_Books:    {book_id} — {len(books)} books (May 2026)")
print(f"{'='*60}")

# Moment type breakdown
from collections import Counter
types = Counter(m["moment_type"] for m in moments)
print("\nPortfolio by type:")
for t, c in types.most_common():
    print(f"  {t}: {c}")

cats = Counter(m["category"] for m in moments)
print("\nPortfolio by category:")
for cat, c in cats.most_common():
    print(f"  {cat}: {c}")

highlights = sum(1 for m in moments if m["is_highlight"])
print(f"\nHighlight moments: {highlights}/{len(moments)}")
print("Done!")
