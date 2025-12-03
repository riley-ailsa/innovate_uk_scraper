#!/usr/bin/env python3
"""
Ingest EU grants into production PostgreSQL + Pinecone.
This replaces your standalone embed_grants.py
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

import psycopg2
import openai
from pinecone import Pinecone
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ailsa-grants")
DATABASE_URL = os.getenv("DATABASE_URL")

openai.api_key = OPENAI_API_KEY

# Initialize clients
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)
pg_conn = psycopg2.connect(DATABASE_URL)


def load_grants(source: str) -> List[Dict[str, Any]]:
    """Load normalized grants from scraper output"""
    file_path = Path(f"data/{source}/normalized.json")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        print(f"   Run scraper first: python -m scraper.pipelines.{source}")
        return []
    
    grants = json.loads(file_path.read_text(encoding='utf-8'))
    print(f"📁 Loaded {len(grants)} grants from {source}")
    return grants


def clean_html(text: str) -> str:
    """Remove HTML tags"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_embedding_text(grant: Dict[str, Any]) -> str:
    """Extract rich text for embedding"""
    parts = []
    
    # Title
    if grant.get('title'):
        parts.append(f"Title: {grant['title']}")
    
    # Programme
    parts.append(f"Programme: {grant['source'].replace('_', ' ').title()}")
    
    # Status and dates
    if grant.get('status'):
        parts.append(f"Status: {grant['status']}")
    
    if grant.get('close_date'):
        parts.append(f"Deadline: {grant['close_date']}")
    
    # Call ID
    if grant.get('call_id'):
        parts.append(f"Call: {grant['call_id']}")
    
    # Extract description from raw
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})
    
    # Description
    description = None
    if 'descriptionByte' in metadata:
        desc_field = metadata['descriptionByte']
        if isinstance(desc_field, list) and len(desc_field) > 0:
            description = desc_field[0]
        elif isinstance(desc_field, str):
            description = desc_field
    
    if description:
        description = clean_html(description)
        if len(description) > 4000:
            description = description[:3500] + "\n...\n" + description[-500:]
        parts.append(f"\nDescription:\n{description}")
    
    # Tags
    if 'crossCuttingPriorities' in metadata:
        priorities = metadata['crossCuttingPriorities']
        if isinstance(priorities, list) and priorities:
            parts.append(f"\nFocus Areas: {', '.join(priorities)}")
    
    return "\n".join(parts)


def extract_tags(grant: Dict[str, Any]) -> List[str]:
    """Extract tags from raw data"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})
    priorities = metadata.get('crossCuttingPriorities', [])
    return priorities if isinstance(priorities, list) else []


def extract_summary(grant: Dict[str, Any]) -> str:
    """Extract description summary (first 500 chars)"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    desc = None
    if 'descriptionByte' in metadata:
        desc_field = metadata['descriptionByte']
        if isinstance(desc_field, list) and len(desc_field) > 0:
            desc = desc_field[0]
        elif isinstance(desc_field, str):
            desc = desc_field

    if desc:
        desc = clean_html(desc)
        return desc[:500] if len(desc) > 500 else desc

    return ''


def extract_budget(grant: Dict[str, Any]) -> tuple[int, int]:
    """Extract budget_min and budget_max from raw data"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    budget = metadata.get('budget', [])
    if isinstance(budget, list) and budget:
        try:
            budget_val = int(budget[0])
            # For now, set both min and max to same value
            # Future: parse budget ranges if available
            return (budget_val, budget_val)
        except (ValueError, TypeError):
            pass

    return (None, None)


def extract_programme_name(grant: Dict[str, Any]) -> str:
    """Extract programme code from identifier (e.g., 'HORIZON-CL5', 'HORIZON-EIT')"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    # Extract from identifier prefix
    if 'identifier' in metadata:
        ident = metadata['identifier']
        if isinstance(ident, list) and ident:
            # e.g., "HORIZON-EIT-2023-25-KIC-EITURBANMOBILITY" -> "HORIZON-EIT"
            parts = ident[0].split('-')
            if len(parts) >= 2:
                return '-'.join(parts[:2])

    return None


def extract_action_type(grant: Dict[str, Any]) -> str:
    """Extract action type from metadata"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    # Check type field
    if 'type' in metadata:
        type_field = metadata['type']
        if isinstance(type_field, list) and type_field:
            return type_field[0]

    return None


def extract_duration(grant: Dict[str, Any]) -> str:
    """Extract project duration"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'duration' in metadata:
        duration = metadata['duration']
        if isinstance(duration, list) and duration:
            # Clean HTML and limit length
            duration_text = clean_html(duration[0])
            return duration_text[:200] if len(duration_text) > 200 else duration_text

    return None


def extract_deadline_model(grant: Dict[str, Any]) -> str:
    """Extract deadline model (single-stage vs multiple cut-off)"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'deadlineModel' in metadata:
        model = metadata['deadlineModel']
        if isinstance(model, list) and model:
            return model[0]

    return None


def extract_identifier(grant: Dict[str, Any]) -> str:
    """Extract official EU identifier"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'identifier' in metadata:
        ident = metadata['identifier']
        if isinstance(ident, list) and ident:
            return ident[0]

    return None


def extract_call_title(grant: Dict[str, Any]) -> str:
    """Extract call title"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'callTitle' in metadata:
        title = metadata['callTitle']
        if isinstance(title, list) and title:
            return title[0]

    return None


def extract_further_info(grant: Dict[str, Any]) -> str:
    """Extract further information (HTML content)"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'furtherInformation' in metadata:
        info = metadata['furtherInformation']
        if isinstance(info, list) and info:
            # Clean HTML and limit length
            info_text = clean_html(info[0])
            return info_text[:1000] if len(info_text) > 1000 else info_text

    return None


def extract_application_info(grant: Dict[str, Any]) -> str:
    """Extract beneficiary administration/application instructions"""
    raw = grant.get('raw', {})
    metadata = raw.get('metadata', {})

    if 'beneficiaryAdministration' in metadata:
        info = metadata['beneficiaryAdministration']
        if isinstance(info, list) and info:
            # Clean HTML and limit length
            info_text = clean_html(info[0])
            return info_text[:1000] if len(info_text) > 1000 else info_text

    return None


def map_status(grant: Dict[str, Any]) -> str:
    """Convert status ID to readable string"""
    status_map = {
        '31094501': 'Forthcoming',
        '31094502': 'Open',
        '31094503': 'Closed'
    }

    status = grant.get('status', '')

    # Status is a string like "['31094502']" - extract the ID
    if isinstance(status, str):
        # Remove brackets and quotes, extract ID
        import re
        match = re.search(r"'(\d+)'", status)
        if match:
            status_id = match.group(1)
            return status_map.get(status_id, 'Unknown')

    # Fallback for actual list format (just in case)
    if isinstance(status, list) and len(status) > 0:
        status_id = status[0]
        return status_map.get(status_id, 'Unknown')

    return 'Unknown'


def ingest_grant(grant: Dict[str, Any]):
    """Ingest one grant into both Postgres and Pinecone"""
    cursor = pg_conn.cursor()

    try:
        # Validate and fix dates
        open_date = grant.get('open_date')
        close_date = grant.get('close_date')

        # Fix invalid dates (close before open)
        if open_date and close_date:
            try:
                from datetime import datetime
                open_dt = datetime.fromisoformat(open_date)
                close_dt = datetime.fromisoformat(close_date)

                if close_dt < open_dt:
                    # Swap them - probably scraped wrong
                    print(f"⚠️  Fixing swapped dates for {grant['id']}")
                    open_date, close_date = close_date, open_date
            except:
                pass  # Invalid date format, keep as is

        # Extract additional fields
        budget_min, budget_max = extract_budget(grant)
        programme = extract_programme_name(grant)
        action_type = extract_action_type(grant)
        duration = extract_duration(grant)
        deadline_model = extract_deadline_model(grant)
        eu_identifier = extract_identifier(grant)
        call_title = extract_call_title(grant)
        further_info = extract_further_info(grant)
        app_info = extract_application_info(grant)
        status = map_status(grant)  # Convert status ID to readable string

        # 1. Insert into PostgreSQL
        cursor.execute("""
            INSERT INTO grants (
                grant_id, source, title, url, call_id,
                status, open_date, close_date, programme,
                tags, description_summary, budget_min, budget_max,
                action_type, duration, deadline_model, eu_identifier,
                call_title, further_information, application_info,
                scraped_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (grant_id) DO UPDATE SET
                status = EXCLUDED.status,
                close_date = EXCLUDED.close_date,
                budget_min = EXCLUDED.budget_min,
                budget_max = EXCLUDED.budget_max,
                action_type = EXCLUDED.action_type,
                duration = EXCLUDED.duration,
                deadline_model = EXCLUDED.deadline_model,
                eu_identifier = EXCLUDED.eu_identifier,
                call_title = EXCLUDED.call_title,
                further_information = EXCLUDED.further_information,
                application_info = EXCLUDED.application_info,
                updated_at = NOW()
        """, (
            grant['id'],
            grant['source'],
            grant['title'],
            grant['url'],
            grant.get('call_id'),
            status,  # Mapped status (Open/Closed/Forthcoming)
            open_date,  # Fixed date
            close_date,  # Fixed date
            programme,  # Extracted from metadata
            extract_tags(grant),
            extract_summary(grant),
            budget_min,  # Extracted from metadata
            budget_max,  # Extracted from metadata
            action_type,  # Extracted from metadata
            duration,  # Extracted from metadata
            deadline_model,  # Extracted from metadata
            eu_identifier,  # Extracted from metadata
            call_title,  # Extracted from metadata
            further_info,  # Extracted from metadata
            app_info,  # Extracted from metadata
        ))

        # Commit IMMEDIATELY after each insert (not batch mode)
        pg_conn.commit()

        # 2. Generate embedding
        text = extract_embedding_text(grant)
        response = openai.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding

        # 3. Upsert to Pinecone
        # Note: Pinecone metadata values must be strings, numbers, or booleans (not None)
        index.upsert(vectors=[{
            'id': grant['id'],
            'values': embedding,
            'metadata': {
                'source': grant['source'],
                'title': grant['title'][:500] if grant.get('title') else '',
                'status': status,  # Mapped status (Open/Closed/Forthcoming)
                'close_date': close_date or '',  # Fixed date
                'programme': programme[:200] if programme else '',
                'url': grant['url'],
                'tags': ','.join(extract_tags(grant)[:5]),  # First 5 tags
                'budget_min': str(budget_min) if budget_min else '',
                'budget_max': str(budget_max) if budget_max else '',
                'action_type': action_type or '',
                'duration': duration[:100] if duration else '',
                'deadline_model': deadline_model or '',
                'eu_identifier': eu_identifier or '',
                'call_title': call_title[:300] if call_title else ''
            }
        }])

        cursor.close()
        return True

    except Exception as e:
        print(f"❌ Error ingesting {grant.get('id')}: {e}")
        pg_conn.rollback()  # Rollback THIS transaction
        cursor.close()
        return False


def ingest_source(source: str):
    """Ingest all grants from a source"""
    print(f"\n{'='*60}")
    print(f"Ingesting: {source}")
    print(f"{'='*60}")

    grants = load_grants(source)
    if not grants:
        return

    success_count = 0
    fail_count = 0

    for grant in tqdm(grants, desc=f"Processing {source}"):
        if ingest_grant(grant):
            success_count += 1
        else:
            fail_count += 1

    # No need to commit here anymore - each grant commits individually

    print(f"\n✅ {source} complete:")
    print(f"   Success: {success_count}")
    print(f"   Failed: {fail_count}")


def main():
    print("="*60)
    print("INGESTING EU GRANTS TO PRODUCTION")
    print("="*60)
    
    start_time = datetime.now()
    
    # Ingest both sources
    ingest_source("horizon_europe")
    ingest_source("digital_europe")
    
    # Get final stats
    cursor = pg_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grants")
    postgres_count = cursor.fetchone()[0]
    cursor.close()
    
    pinecone_stats = index.describe_index_stats()
    pinecone_count = pinecone_stats['total_vector_count']
    
    duration = (datetime.now() - start_time).total_seconds()
    
    print(f"\n{'='*60}")
    print("INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Duration: {duration:.1f}s")
    print(f"PostgreSQL grants: {postgres_count}")
    print(f"Pinecone vectors: {pinecone_count}")
    
    pg_conn.close()


if __name__ == "__main__":
    main()