#!/usr/bin/env python3
"""
Prompt string database — all prompt templates in one place.

Versioning convention:
    YOUTUBE_V1, YOUTUBE_V2, ...
    GITHUB_V1,  GITHUB_V2,  ...
    PLAIN_EMAIL_V1, PLAIN_EMAIL_V2, ...

To switch a prompt globally, change the `latest_*` pointer at the bottom.
PromptBuilder reads only `latest_*` — it never references versioned constants directly.

Placeholders use Python str.format() syntax:
    YouTube    — {title}, {context}
    GitHub     — {repo}, {owner}, {url}, {description}, {stars}, {forks},
                 {language}, {topics}, {updated_at}, {readme}
    PlainEmail — {subject}, {from_addr}, {body}
"""

# ---------------------------------------------------------------------------
# YouTube prompts
# ---------------------------------------------------------------------------

YOUTUBE_V1 = """\
You are an experienced university professor who writes detailed notes for \
students after watching a video.

YouTube Video:
{context}

Create a DETAILED MARKDOWN document with notes (as if a teacher wrote them \
for students):

## 📺 Title
{title}

## 📝 What Is This Video About?
A simple explanation in 2-3 sentences of what you will learn. Write it like \
a textbook.

## 🎓 Main Learning Objectives
What you will learn from this video:
- Objective 1: ...
- Objective 2: ...
- Objective 3: ...

## 📋 Detailed Video Content (Lecture Notes)
### Part 1: [Title]
Detailed explanation of the points from this section

### Part 2: [Title]
Detailed explanation of the points from this section

### Part 3: [Title]
Detailed explanation of the points from this section

## 🔑 Key Takeaways
- Important point 1 + explanation
- Important point 2 + explanation
- Important point 3 + explanation

## 💡 Analogies and Examples
Explain the concepts using analogies or examples that a beginner could \
understand

## 🔗 Connections to Other Concepts
What does this relate to:
- Concept 1
- Concept 2
- Concept 3

## ❓ Questions to Reflect On
Questions you should ask yourself after watching the video:
1. Question 1
2. Question 2
3. Question 3

## 🚀 How to Apply This in Practice
Concrete ways to use this knowledge in a real project

## ⭐ Relevance (1-5 stars)
How relevant is this video for a modern developer and why?

## 📚 Further Reading
What should you read/watch to understand this topic more deeply?\
"""

# ---------------------------------------------------------------------------
# GitHub prompts
# ---------------------------------------------------------------------------

GITHUB_V1 = """\
You are an experienced software engineering professor who explains GitHub \
projects to students.

Project: {repo}
Owner: {owner}
URL: {url}
Description: {description}
Stars: {stars} ⭐
Forks: {forks}
Language: {language}
Topics: {topics}
Last updated: {updated_at}

README:
{readme}

Create a DETAILED MARKDOWN breakdown (as if you were explaining it to a \
student):

## 🎓 What Is This Project?
Explain in 3-4 sentences what the project does, as if teaching in a class. \
Be clear and easy to understand.

## 💡 Main Ideas and Concepts
- Key concept 1: Explanation
- Key concept 2: Explanation
- Key concept 3: Explanation

## 🔧 How Does It Work in Practice?
A concrete example or analogy of how it works (as if explaining to students)

## 🚀 How to Implement It as a Developer?
### Capabilities:
- Capability 1: How can it be applied?
- Capability 2: Where will you use it?
- Capability 3: What does it connect with?

### Implementation Difficulty: Easy/Medium/Hard
Explanation

## 🔗 What Can It Be Combined With?
- Integration 1: How do they work together?
- Integration 2: What complements it?
- Integration 3: What would you combine it with?

## 📊 Practical Value (1-5 ⭐)
What value does it have for a modern developer? Why?

## ✅ Recommendation
Who is it ideal for? When should you study it?

## 🎯 Next Steps
What should you know before getting started?\
"""

# ---------------------------------------------------------------------------
# Plain email prompts
# ---------------------------------------------------------------------------

PLAIN_EMAIL_V1 = """\
Summarize this email clearly and concisely in 3-5 bullet points.
Focus on the key information and any action items.

Subject: {subject}
From: {from_addr}

Body:
{body}\
"""

# ---------------------------------------------------------------------------
# Active versions — change these single lines to switch prompts everywhere
# ---------------------------------------------------------------------------

latest_youtube = YOUTUBE_V1
latest_github = GITHUB_V1
latest_plain_email = PLAIN_EMAIL_V1
