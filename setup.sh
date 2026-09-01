export PATH="$HOME/.local/bin:$PATH"
export $(grep -v "^#" .env | xargs)
