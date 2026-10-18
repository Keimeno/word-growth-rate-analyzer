# mongo >= 6 only ships mongosh, older images only ship the legacy mongo shell
MONGO_SHELL=$(command -v mongosh || command -v mongo)

"$MONGO_SHELL" --quiet \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  "$MONGO_INITDB_DATABASE" \
  --eval "db.createUser({ user: '$MONGO_INITDB_USERNAME', pwd: '$MONGO_INITDB_PASSWORD', roles: [{ role: 'readWrite', db: '$MONGO_INITDB_DATABASE' }] });"
