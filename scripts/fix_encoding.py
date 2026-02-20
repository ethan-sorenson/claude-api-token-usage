"""Fix double-encoded UTF-8 in app.js by replacing mojibake with HTML entities."""
import re

filepath = r'c:\Users\EthanSorenson\OneDrive - eOne Integrated Business Solutions\eOneNavExtension\claude-api-token-usage\static\js\app.js'

with open(filepath, 'r', encoding='utf-8-sig') as f:
    content = f.read()

lines = content.split('\n')
fixed_lines = []

for line in lines:
    # Status indicator dots
    line = re.sub(r"<span>[^\x00-\x7f]+</span>", "<span>&#9679;</span>", line)
    
    # Collapse/expand arrows
    if "collapsed ? '" in line and "' : '" in line:
        line = re.sub(r"collapsed \? '[^\x00-\x7f]+' : '[^\x00-\x7f]+'",
                      "collapsed ? '&#9654;' : '&#9660;'", line)
    
    # Button: Test Connection (pin icon)
    if 'Test Connection' in line and '>' in line:
        line = re.sub(r'>\s*$', '>&#128204;', line.rstrip())
    
    # Button: Configure Tools (gear icon)  
    if 'Configure Tools' in line and '>' in line:
        line = re.sub(r'>\s*$', '>&#9881;&#65039;', line.rstrip())
    
    # Button: Remove Server (trash icon)
    if 'Remove Server' in line and '>' in line:
        line = re.sub(r'>\s*$', '>&#128465;&#65039;', line.rstrip())
    
    # Remove header × button
    line = re.sub(r'title="Remove header">[^\x00-\x7f]+</button>',
                  'title="Remove header">&times;</button>', line)
    
    # Auth section lock icon before authTypeConfig.name
    line = re.sub(r'[^\x00-\x7f]+ \$\{authTypeConfig\.name\}',
                  '&#128274; ${authTypeConfig.name}', line)
    
    # Thinking spinner
    line = re.sub(r'>[^\x00-\x7f]+</span> Thinking',
                  '>&#129300;</span> Thinking', line)
    
    # Truncated/Paused warning innerHTML
    line = re.sub(r'innerHTML = `[^\x00-\x7f]+ <strong>Response Truncated',
                  'innerHTML = `&#9888;&#65039; <strong>Response Truncated', line)
    line = re.sub(r'innerHTML = `[^\x00-\x7f]+ <strong>Conversation Paused',
                  'innerHTML = `&#9209;&#65039; <strong>Conversation Paused', line)
    
    # Tool call spans
    if 'toolCall' in line:
        line = re.sub(r'<span>[^\x00-\x7f]+</span>', '<span>&#9881;</span>', line)
    
    # showError calls - strip emoji prefixes, keep the message
    line = re.sub(r"showError\('[^\x00-\x7f]+ (INFO|WARNING|Please|Opening|Generating|Copied)",
                  r"showError('\1", line)
    line = re.sub(r"showError\(`[^\x00-\x7f]+ (OAuth|Failed|Connection|Server Error|Test All|"
                  r"Session|Error|No authorization|Testing|Tested)",
                  r"showError(`\1", line)
    line = re.sub(r"showError\(`[^\x00-\x7f]+ \$\{server",
                  "showError(`${server", line)
    line = re.sub(r"showError\(`[^\x00-\x7f]+ \$\{result",
                  "showError(`${result", line)
    
    # successMsg assignments
    line = re.sub(r"successMsg = `[^\x00-\x7f]+ OAuth",
                  "successMsg = `OAuth", line)
    line = re.sub(r"successMsg = `[^\x00-\x7f]+ \$\{result",
                  "successMsg = `${result", line)
    line = re.sub(r"successMsg \+= `[^\x00-\x7f]*\\n[^\x00-\x7f]+ Prompts",
                  "successMsg += `\\nPrompts", line)
    line = re.sub(r"successMsg \+= `[^\x00-\x7f]*\\n[^\x00-\x7f]+ Tools",
                  "successMsg += `\\nTools", line)
    line = re.sub(r"successMsg \+= `[^\x00-\x7f]+ Prompts",
                  "successMsg += `Prompts", line)
    line = re.sub(r"successMsg \+= `[^\x00-\x7f]+ Tools",
                  "successMsg += `Tools", line)
    
    # console.log emoji prefix
    line = re.sub(r"console\.log\(`[^\x00-\x7f]+ API Request",
                  "console.log(`API Request", line)
    
    # message += lines
    line = re.sub(r"message \+= `[^\x00-\x7f]+ Tested",
                  "message += `Tested", line)
    line = re.sub(r"message \+= `  [^\x00-\x7f]+ ",
                  "message += `  - ", line)
    
    # Prompts dialog icons
    line = re.sub(r"'>[^\x00-\x7f]+ Prompts</button>",
                  "'>&#128221; Prompts</button>", line)
    
    # Final cleanup: remove any remaining isolated mojibake (3+ non-ASCII chars in a row)
    line = re.sub(r'[^\x00-\x7f]{3,}', '', line)
    
    fixed_lines.append(line)

fixed = '\n'.join(fixed_lines)

# Verify no mojibake remains
remaining = [(i+1, l.strip()[:60]) for i, l in enumerate(fixed.split('\n'))
             if any(ord(c) > 127 for c in l)]
print(f"Lines with remaining non-ASCII: {len(remaining)}")
for ln, text in remaining[:10]:
    print(f"  L{ln}: {text}")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(fixed)
print("File saved successfully")
