from app.services.pdf_import import _extract_authors, PageText, TitleMatch

pages = [
    PageText(
        number=0,
        text="The title of the paper\nAbstract\nThis paper studies the topic.\nA. B. Ivanov, C. D. Petrov\nInstitute of Earth Sciences",
        lines=[
            "The title of the paper",
            "Abstract",
            "This paper studies the topic.",
            "A. B. Ivanov, C. D. Petrov",
            "Institute of Earth Sciences",
        ],
    )
]

print(
    _extract_authors(
        pages,
        title_match=TitleMatch(
            title="The title of the paper",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )
)
