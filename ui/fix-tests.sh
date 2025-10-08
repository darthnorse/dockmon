#!/bin/bash
# Fix all tests to wait for form to load by using findBy instead of getBy
sed -i '' 's/screen\.getByLabelText(\/username\/i)/await screen.findByLabelText(\/username\/i)/g' src/features/auth/LoginPage.test.tsx
sed -i '' 's/screen\.getByRole('\''button'\'', { name: \/log in\/i })/await screen.findByRole('\''button'\'', { name: \/log in\/i })/g' src/features/auth/LoginPage.test.tsx
