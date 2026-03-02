from typing import List
from flashcard.services.i18n import i18n

def format_expression_list(expressions: List[str], plain: bool = False, sort_alphabetical: bool = True) -> List[str]:
    """
    Formats a list of expressions into one or more Telegram messages.
    Telegram limit is 4096 chars. We stay safer with ~4000.
    """
    if not expressions:
        return [i18n.get("messages.collection.empty")] 

    # Sort alphabetically if requested (default behavior)
    if sort_alphabetical:
        expressions.sort(key=lambda s: s.lower())

    if plain:
        # Plain mode: Simple header, no grouping, no fancy bullets
        header = i18n.get("messages.collection.header", count=len(expressions))
        bullet = ""
        footer = ""
    else:
        # Fancy mode
        header = i18n.get("messages.collection.header", count=len(expressions))
        bullet = "" # Minimal bullet
        footer = ""

    messages = []
    current_chunk = header
    
    last_char = ""
    
    for expr in expressions:
        # Grouping by letter only in Fancy mode AND when sorted alphabetically
        if not plain and sort_alphabetical:
            first_char = expr[0].upper()
            if first_char != last_char and first_char.isalpha():
                # Add section header
                section_header = f"\n<b>{first_char}</b>\n"
                if len(current_chunk) + len(section_header) > 4000:
                    messages.append(current_chunk)
                    current_chunk = section_header
                else:
                    current_chunk += section_header
                last_char = first_char
            
        if plain:
             line = f"{expr}\n"
        else:
             line = f"{bullet}{expr}\n"
        
        # Check limit
        if len(current_chunk) + len(line) > 4000:
            messages.append(current_chunk)
            current_chunk = line
        
        current_chunk += line
    
    if footer:
        if len(current_chunk) + len(footer) <= 4000:
            current_chunk += footer
        else:
            messages.append(current_chunk)
            current_chunk = footer

    if current_chunk:
        messages.append(current_chunk)
        
    return messages
