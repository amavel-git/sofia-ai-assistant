#!/usr/bin/env python3
"""
Sofia Site Graph

Phase 4.2B

Purpose
-------
Convert a site's page inventory into a semantic knowledge graph.

This module is intentionally language agnostic.

It does NOT know:

- Spanish
- English
- URLs conventions
- WordPress
- Workspace configuration

It only organizes semantic page relationships.

Future consumers:

- navigation_resolver.py
- content_critic.py
- maintenance_intelligence.py
- internal_linking.py
- opportunity_discovery.py
"""

from collections import defaultdict
from typing import Dict, List, Any


SITE_GRAPH_VERSION = "1.0"


def build_site_graph(site_structure: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert site_structure.json into a semantic graph.

    Parameters
    ----------
    site_structure : dict

    Returns
    -------
    dict
        Semantic knowledge graph.
    """

    graph = {
        "version": SITE_GRAPH_VERSION,

        #
        # General indexes
        #
        "pages": [],
        "by_page_type": defaultdict(list),
        "by_topic": defaultdict(list),
        "by_section": defaultdict(list),

        #
        # Semantic groups
        #
        "authority_pages": [],
        "methodology_pages": [],
        "faq_pages": [],
        "pricing_pages": [],
        "service_pages": [],
        "city_pages": [],
        "blog_posts": [],
        "educational_pages": [],
    }

    for page in site_structure.get("pages", []):

        graph["pages"].append(page)

        page_type = page.get("page_type", "")
        topic = page.get("topic", "")
        section = page.get("section", "")

        graph["by_page_type"][page_type].append(page)
        graph["by_topic"][topic].append(page)
        graph["by_section"][section].append(page)

        #
        # Semantic classification
        #

        if page_type == "faq_page":
            graph["faq_pages"].append(page)

        elif page_type == "pricing_page":
            graph["pricing_pages"].append(page)

        elif page_type == "service_page":
            graph["service_pages"].append(page)

        elif page_type == "city_page":
            graph["city_pages"].append(page)

        elif page_type == "blog_post":
            graph["blog_posts"].append(page)

        elif page_type == "info_page":
            graph["educational_pages"].append(page)

            topic_name = (topic or "").lower()

            if topic_name.startswith("science"):
                graph["authority_pages"].append(page)

            elif topic_name == "history":
                graph["authority_pages"].append(page)

            elif topic_name == "general_polygraph":
                graph["methodology_pages"].append(page)

    #
    # Convert defaultdicts into normal dicts
    #

    graph["by_page_type"] = dict(graph["by_page_type"])
    graph["by_topic"] = dict(graph["by_topic"])
    graph["by_section"] = dict(graph["by_section"])

    return graph


def find_pages_by_type(
    graph: Dict[str, Any],
    page_type: str,
) -> List[Dict[str, Any]]:

    return graph.get("by_page_type", {}).get(page_type, [])


def find_pages_by_topic(
    graph: Dict[str, Any],
    topic: str,
) -> List[Dict[str, Any]]:

    return graph.get("by_topic", {}).get(topic, [])


def get_semantic_group(
    graph: Dict[str, Any],
    group: str,
) -> List[Dict[str, Any]]:

    return graph.get(group, [])


if __name__ == "__main__":

    print(
        "Site Graph Module\n"
        "Import this module from navigation_resolver.py."
    )
