

result =""

for i in range(324,328):
    result += '''
        {
            "name": "A'''+str(i)+ '''",
            "floor": 0,
            "walls": 2.3
        },'''
        
print(result)